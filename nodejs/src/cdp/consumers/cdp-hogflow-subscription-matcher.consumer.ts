import { Message } from 'node-rdkafka'
import { Pool } from 'pg'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'

import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { HogFlow, HogFlowAction } from '../../schema/hogflow'
import { HealthCheckResult, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { HogFlowInvocationContext, HogFunctionInvocationGlobals } from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { execHog } from '../utils/hog-exec'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpConsumerBase, CdpConsumerBaseConfig, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

type ParkedCandidate = {
    id: string
    teamId: number
    functionId: string
    actionId: string | null
    distinctId: string
}

type WakeRequest = {
    id: string
    stepMatched: boolean
    conversionMatched: boolean
}

/**
 * Dedicated consumer that matches incoming events against parked hogflow jobs and
 * wakes them when either:
 *   - The job is parked at a `wait_until_condition` step whose events or condition
 *     filters match the incoming event (sets `currentAction.eventMatched`).
 *   - The workflow has event-based conversion goals configured and the incoming
 *     event matches one (sets `state.conversionMatched`, executor exits early).
 *
 * For each event batch the consumer:
 * 1. Finds parked hogflow jobs for the event's distinct_id via cyclotron_jobs
 * 2. Loads the hogflow config from cache (HogFlowManager) for each job
 * 3. Evaluates the parked step's filters and the workflow's conversion events
 * 4. Wakes matching jobs in a single batched UPDATE
 *
 * Lives in its own deployment so failures talking to the Cyclotron V2 database do
 * not block `cdp-events-consumer`. If `CYCLOTRON_NODE_DATABASE_URL` is unset, the
 * consumer is a no-op (safe to run where V2 is not configured).
 */
export class CdpHogflowSubscriptionMatcherConsumer extends CdpConsumerBase {
    protected name = 'CdpHogflowSubscriptionMatcherConsumer'
    protected kafkaConsumer: KafkaConsumer
    private cyclotronPool: Pool | null = null

    constructor(config: CdpConsumerBaseConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        this.kafkaConsumer = new KafkaConsumer({
            groupId: 'cdp-hogflow-subscription-matcher-consumer',
            topic: KAFKA_EVENTS_JSON,
        })

        if (config.CYCLOTRON_NODE_DATABASE_URL) {
            this.cyclotronPool = new Pool({
                connectionString: config.CYCLOTRON_NODE_DATABASE_URL,
                max: 5,
            })
        }
    }

    public async processBatch(invocationGlobals: HogFunctionInvocationGlobals[]): Promise<void> {
        if (!invocationGlobals.length) {
            return
        }
        await this.wakeMatchingWorkflows(invocationGlobals)
    }

    @instrumented('cdpHogflowSubscriptionMatcher.wakeMatchingWorkflows')
    private async wakeMatchingWorkflows(invocationGlobals: HogFunctionInvocationGlobals[]): Promise<void> {
        if (!this.cyclotronPool) {
            return
        }

        const globalsByKey = new Map<string, HogFunctionInvocationGlobals>()

        for (const globals of invocationGlobals) {
            const distinctId = globals.event.distinct_id
            if (!distinctId) {
                continue
            }
            const key = `${globals.project.id}:${distinctId}`
            if (!globalsByKey.has(key)) {
                globalsByKey.set(key, globals)
            }
        }

        if (globalsByKey.size === 0) {
            return
        }

        const teamIds = [...new Set([...globalsByKey.values()].map((g) => g.project.id))]
        const distinctIds = [...new Set([...globalsByKey.values()].map((g) => g.event.distinct_id))]

        const candidates = await this.findParkedJobs(teamIds, distinctIds)
        if (candidates.length === 0) {
            return
        }

        const hogflowIds = [...new Set(candidates.map((c) => c.functionId))]
        const hogflows = await this.hogFlowManager.getHogFlows(hogflowIds)

        const jobsToWake: WakeRequest[] = []

        for (const candidate of candidates) {
            const hogflow = hogflows[candidate.functionId]
            if (!hogflow) {
                continue
            }

            const globals = globalsByKey.get(`${candidate.teamId}:${candidate.distinctId}`)
            if (!globals) {
                continue
            }

            const filterGlobals = convertToHogFunctionFilterGlobal(globals)
            const action = candidate.actionId
                ? hogflow.actions.find((a: HogFlowAction) => a.id === candidate.actionId)
                : undefined

            const stepMatched =
                action?.type === 'wait_until_condition'
                    ? await this.evaluateWaitUntilCondition(action, filterGlobals, globals.event.event)
                    : false

            const conversionMatched = await this.evaluateConversionEvents(hogflow, filterGlobals, globals.event.event)

            if (stepMatched || conversionMatched) {
                jobsToWake.push({ id: candidate.id, stepMatched, conversionMatched })
            }
        }

        if (jobsToWake.length === 0) {
            return
        }

        const woken = await this.wakeJobs(jobsToWake)
        logger.info('⚡', 'Woke waiting workflows from event match', {
            evaluated: candidates.length,
            matched: jobsToWake.length,
            woken,
        })
    }

    /**
     * Evaluate a wait_until_condition step's filters against the incoming event.
     * Either an event match or a property condition match wakes the step.
     */
    private async evaluateWaitUntilCondition(
        action: Extract<HogFlowAction, { type: 'wait_until_condition' }>,
        filterGlobals: ReturnType<typeof convertToHogFunctionFilterGlobal>,
        incomingEventName: string
    ): Promise<boolean> {
        for (const eventConfig of action.config.events ?? []) {
            if (await this.evaluateEventConfig(eventConfig, filterGlobals, incomingEventName, action.id)) {
                return true
            }
        }

        const bytecode = action.config.condition?.filters?.bytecode
        if (Array.isArray(bytecode) && bytecode.length > 0) {
            try {
                const result = await execHog(bytecode, { globals: filterGlobals })
                if (result.execResult?.result === true) {
                    return true
                }
            } catch (err) {
                logger.warn('Filter evaluation error for wait_until_condition', {
                    actionId: action.id,
                    error: String(err),
                })
            }
        }

        return false
    }

    /**
     * Evaluate the workflow's event-based conversion goals against the incoming event.
     * A match here causes the executor to exit the workflow early on next pickup.
     */
    private async evaluateConversionEvents(
        hogflow: HogFlow,
        filterGlobals: ReturnType<typeof convertToHogFunctionFilterGlobal>,
        incomingEventName: string
    ): Promise<boolean> {
        const conversionEvents = (hogflow.conversion as any)?.events ?? []
        for (const eventConfig of conversionEvents) {
            if (
                await this.evaluateEventConfig(
                    eventConfig,
                    filterGlobals,
                    incomingEventName,
                    `${hogflow.id}/conversion`
                )
            ) {
                return true
            }
        }
        return false
    }

    private async evaluateEventConfig(
        eventConfig: { filters?: any },
        filterGlobals: ReturnType<typeof convertToHogFunctionFilterGlobal>,
        incomingEventName: string,
        contextId: string
    ): Promise<boolean> {
        const bytecode = eventConfig.filters?.bytecode
        if (Array.isArray(bytecode) && bytecode.length > 0) {
            try {
                const result = await execHog(bytecode, { globals: filterGlobals })
                return result.execResult?.result === true
            } catch (err) {
                logger.warn('Event filter evaluation error', { contextId, error: String(err) })
                return false
            }
        }

        // No bytecode: match on event name alone. Empty event list matches nothing.
        const configuredNames = extractEventNames(eventConfig.filters)
        return configuredNames.includes(incomingEventName)
    }

    /**
     * Find parked hogflow jobs for the given team_ids and distinct_ids. Projects only
     * the metadata needed for the matching decision; state is loaded later for the
     * subset we actually wake.
     */
    private async findParkedJobs(teamIds: number[], distinctIds: string[]): Promise<ParkedCandidate[]> {
        if (!this.cyclotronPool) {
            return []
        }

        const result = await this.cyclotronPool.query(
            `SELECT id, team_id, function_id, action_id, distinct_id
             FROM cyclotron_jobs
             WHERE status = 'available'
               AND queue_name = 'hogflow'
               AND scheduled > NOW()
               AND team_id = ANY($1::int[])
               AND distinct_id = ANY($2::text[])`,
            [teamIds, distinctIds]
        )

        return result.rows.map((row) => ({
            id: row.id,
            teamId: row.team_id,
            functionId: row.function_id,
            actionId: row.action_id,
            distinctId: row.distinct_id,
        }))
    }

    /**
     * Wake jobs by loading their state, setting eventMatched/conversionMatched flags,
     * and updating with scheduled = NOW(). Only affects jobs still 'available'.
     */
    private async wakeJobs(requests: WakeRequest[]): Promise<number> {
        if (!this.cyclotronPool || requests.length === 0) {
            return 0
        }

        const ids = requests.map((r) => r.id)
        const stateRows = await this.cyclotronPool.query(
            `SELECT id, state FROM cyclotron_jobs
             WHERE id = ANY($1::uuid[]) AND status = 'available'`,
            [ids]
        )

        const requestById = new Map(requests.map((r) => [r.id, r]))
        const updates: { id: string; state: Buffer }[] = []

        for (const row of stateRows.rows) {
            if (!row.state) {
                continue
            }
            const req = requestById.get(row.id)
            if (!req) {
                continue
            }
            try {
                const parsed = parseJSON(row.state.toString('utf-8'))
                const updatedState: HogFlowInvocationContext = { ...parsed.state }
                if (req.stepMatched && updatedState.currentAction) {
                    updatedState.currentAction = { ...updatedState.currentAction, eventMatched: true }
                }
                if (req.conversionMatched) {
                    updatedState.conversionMatched = true
                }
                parsed.state = updatedState
                updates.push({ id: row.id, state: Buffer.from(JSON.stringify(parsed)) })
            } catch (err) {
                logger.warn('Failed to parse state during wake', { jobId: row.id, error: String(err) })
            }
        }

        if (updates.length === 0) {
            return 0
        }

        const result = await this.cyclotronPool.query(
            `UPDATE cyclotron_jobs cj
             SET scheduled = NOW(), state = u.state
             FROM (
                 SELECT unnest($1::uuid[]) AS id, unnest($2::bytea[]) AS state
             ) u
             WHERE cj.id = u.id AND cj.status = 'available'`,
            [updates.map((u) => u.id), updates.map((u) => u.state)]
        )
        return result.rowCount ?? 0
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

    public override async start(): Promise<void> {
        await super.start()
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('cdpHogflowSubscriptionMatcher.handleEachBatch', async () => {
                const invocationGlobals = await this._parseKafkaBatch(messages)
                const backgroundTask = this.processBatch(invocationGlobals).catch((err) => {
                    captureException(err)
                    logger.error('🔴', 'Error matching workflows', { err })
                })
                return { backgroundTask }
            })
        })
    }

    public override async stop(): Promise<void> {
        logger.info('💤', `Stopping ${this.name}...`)
        await this.kafkaConsumer.disconnect()
        if (this.cyclotronPool) {
            await this.cyclotronPool.end()
        }
        await super.stop()
        logger.info('💤', `${this.name} stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}

function extractEventNames(filters: any): string[] {
    if (!filters || typeof filters !== 'object') {
        return []
    }
    const events = filters.events
    if (!Array.isArray(events) || events.length === 0) {
        return []
    }
    return events
        .map((e: any) => (e && typeof e === 'object' ? (e.id ?? e.name ?? '') : ''))
        .filter((name: string) => name !== '')
}
