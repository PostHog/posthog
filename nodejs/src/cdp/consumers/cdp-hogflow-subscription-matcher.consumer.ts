import { Message } from 'node-rdkafka'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'

import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { EventSubscription } from '../services/hogflows/event-subscriptions.service'
import { HogFunctionInvocationGlobals } from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { execHog } from '../utils/hog-exec'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpConsumerBase, CdpConsumerBaseConfig, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

/**
 * Dedicated consumer that matches incoming events against `wait_until_event`
 * and event-based conversion subscriptions and wakes the corresponding
 * workflow jobs.
 *
 * Lives in its own deployment so that failures talking to the Cyclotron V2
 * database do not block `cdp-events-consumer` (which feeds destinations and
 * workflow triggers).
 */
export class CdpHogflowSubscriptionMatcherConsumer extends CdpConsumerBase {
    protected name = 'CdpHogflowSubscriptionMatcherConsumer'
    protected kafkaConsumer: KafkaConsumer

    constructor(config: CdpConsumerBaseConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        this.kafkaConsumer = new KafkaConsumer({
            groupId: 'cdp-hogflow-subscription-matcher-consumer',
            topic: KAFKA_EVENTS_JSON,
        })
    }

    public async processBatch(invocationGlobals: HogFunctionInvocationGlobals[]): Promise<void> {
        if (!invocationGlobals.length) {
            return
        }
        await this.wakeWaitingWorkflows(invocationGlobals)
    }

    /**
     * For each event in the batch, look up any waiting subscriptions for
     * the same team + event_name + person_id, evaluate their property filters
     * against the event, and wake any matched workflow jobs.
     */
    @instrumented('cdpHogflowSubscriptionMatcher.wakeWaitingWorkflows')
    private async wakeWaitingWorkflows(invocationGlobals: HogFunctionInvocationGlobals[]): Promise<void> {
        const subscriptionsService = this.eventSubscriptionsService
        if (!subscriptionsService) {
            return
        }

        const tuples: { teamId: number; eventName: string; personId: string }[] = []
        const globalsByKey = new Map<string, HogFunctionInvocationGlobals>()

        for (const globals of invocationGlobals) {
            const personId = globals.person?.id
            if (!personId) {
                continue
            }
            const key = `${globals.project.id}:${globals.event.event}:${personId}`
            if (!globalsByKey.has(key)) {
                tuples.push({
                    teamId: globals.project.id,
                    eventName: globals.event.event,
                    personId: String(personId),
                })
                globalsByKey.set(key, globals)
            }
        }

        if (tuples.length === 0) {
            return
        }

        const candidates = await subscriptionsService.findMatchingForEvents(tuples)
        if (candidates.length === 0) {
            return
        }

        const matches: { jobId: string; type: (typeof candidates)[0]['type'] }[] = []
        for (const candidate of candidates) {
            const key = `${candidate.teamId}:${candidate.eventName}:${candidate.personId}`
            const globals = globalsByKey.get(key)
            if (!globals) {
                continue
            }
            const filterGlobals = convertToHogFunctionFilterGlobal(globals)
            const matched = await this.evaluateSubscriptionFilters(candidate, filterGlobals)
            if (matched) {
                matches.push({ jobId: candidate.jobId, type: candidate.type })
            }
        }

        if (matches.length === 0) {
            return
        }

        const woken = await subscriptionsService.wakeJobs(matches)
        logger.info('⚡', 'Woke waiting workflows from event match', {
            matched: matches.length,
            woken,
        })
    }

    /**
     * Evaluate a subscription's filter bytecode against the incoming event.
     * If no bytecode is present, the subscription matches on event_name alone
     * (which the DB lookup already enforces).
     */
    private async evaluateSubscriptionFilters(
        subscription: EventSubscription,
        filterGlobals: ReturnType<typeof convertToHogFunctionFilterGlobal>
    ): Promise<boolean> {
        if (!subscription.bytecode || !Array.isArray(subscription.bytecode) || subscription.bytecode.length === 0) {
            return true
        }

        try {
            const result = await execHog(subscription.bytecode, { globals: filterGlobals })
            if (result.error || !result.execResult || result.execResult.error) {
                logger.warn('Subscription bytecode error, treating as no-match', {
                    subscriptionId: subscription.id,
                    error: String(result.error ?? result.execResult?.error),
                })
                return false
            }
            return result.execResult.result === true
        } catch (err) {
            logger.warn('Subscription filter evaluation threw, treating as no-match', {
                subscriptionId: subscription.id,
                error: String(err),
            })
            return false
        }
    }

    @instrumented('cdpHogflowSubscriptionMatcher.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const events: HogFunctionInvocationGlobals[] = []

        await Promise.all(
            messages.map(async (message) => {
                try {
                    const clickHouseEvent = parseJSON(message.value!.toString()) as RawClickHouseEvent

                    if (!clickHouseEvent.person_id) {
                        return
                    }

                    const team = await this.deps.teamManager.getTeam(clickHouseEvent.team_id)
                    if (!team) {
                        return
                    }

                    events.push(convertToHogFunctionInvocationGlobals(clickHouseEvent, team, this.config.SITE_URL))
                } catch (e) {
                    logger.error('Error parsing message', e)
                    counterParseError.labels({ error: e.message }).inc()
                }
            })
        )

        return events
    }

    public async start(): Promise<void> {
        await super.start()
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('cdpHogflowSubscriptionMatcher.handleEachBatch', async () => {
                const invocationGlobals = await this._parseKafkaBatch(messages)
                const backgroundTask = this.processBatch(invocationGlobals).catch((err) => {
                    captureException(err)
                    logger.error('🔴', 'Error matching subscriptions', { err })
                })
                return { backgroundTask }
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('💤', `Stopping ${this.name}...`)
        await this.kafkaConsumer.disconnect()
        await super.stop()
        logger.info('💤', `${this.name} stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
