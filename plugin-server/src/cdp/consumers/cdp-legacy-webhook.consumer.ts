import { Message } from 'node-rdkafka'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { KafkaConsumer } from '~/kafka/consumer'

import {
    Action,
    HealthCheckResult,
    Hook,
    HookPayload,
    Hub,
    PostIngestionEvent,
    RawClickHouseEvent,
    Team,
} from '../../types'
import { PostgresUse } from '../../utils/db/postgres'
import { convertToHookPayload, convertToPostIngestionEvent } from '../../utils/event'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { ActionManager } from '../legacy-webhooks/action-manager'
import { ActionMatcher } from '../legacy-webhooks/action-matcher'
import { addGroupPropertiesToPostIngestionEvent } from '../legacy-webhooks/utils'
import { cdpTrackedFetch } from '../services/hog-executor.service'
import { CdpConsumerBase } from './cdp-base.consumer'
import { counterParseError } from './metrics'

/**
 * This consumer processes webhook events from the legacy webhooks system - this is the "hooks" table that used to be filled via Zapier.
 * Now the only path for creation is via a hog function but this just exists for now to keep non-migrated webhooks working.
 */

export class CdpLegacyWebhookConsumer extends CdpConsumerBase {
    protected name = 'CdpLegacyWebhookConsumer'
    protected promiseScheduler = new PromiseScheduler()
    protected kafkaConsumer: KafkaConsumer
    protected actionMatcher: ActionMatcher

    constructor(hub: Hub) {
        super(hub)

        this.kafkaConsumer = new KafkaConsumer({
            groupId: hub.CDP_LEGACY_WEBHOOK_CONSUMER_GROUP_ID,
            topic: hub.CDP_LEGACY_WEBHOOK_CONSUMER_TOPIC,
        })

        this.actionMatcher = new ActionMatcher(new ActionManager(hub.postgres, hub.pubSub))

        logger.info('🔁', `CdpLegacyWebhookConsumer setup`)
    }

    @instrumented('cdpLegacyWebhookConsumer.processEvent')
    public async processEvent(event: PostIngestionEvent) {
        const actionMatches = this.actionMatcher.match(event)
        if (!actionMatches.length) {
            return
        }

        await this.fireWebhooks(event, actionMatches)
    }

    private async fireWebhooks(event: PostIngestionEvent, actionMatches: Action[]): Promise<void> {
        const team = await this.hub.teamManager.getTeam(event.teamId)

        if (!team) {
            return
        }

        if (await this.hub.teamManager.hasAvailableFeature(team.id, 'zapier')) {
            const restHooks = actionMatches.flatMap((action) => action.hooks.map((hook) => ({ hook, action })))

            if (restHooks.length > 0) {
                const restHookRequests = restHooks.map(({ hook }) => this.postWebhook(event, team, hook))
                await Promise.all(restHookRequests)
            }
        }
    }

    private async postWebhook(event: PostIngestionEvent, team: Team, hook: Hook): Promise<void> {
        const defaultWebhookUrl = team.slack_incoming_webhook
        const url = hook ? hook.target : defaultWebhookUrl

        if (!url) {
            return
        }

        const body: HookPayload = {
            hook: { id: hook.id, event: hook.event, target: hook.target },
            data: convertToHookPayload(event),
        }

        logger.debug('⚠️', `Firing webhook ${url} for team ${team.id}`)

        const response = await cdpTrackedFetch({
            url,
            fetchParams: {
                method: 'POST',
                body: JSON.stringify(body, null, 4),
                headers: { 'Content-Type': 'application/json' },
            },
            templateId: 'legacy-zapier-webhook',
        })

        if (response.fetchError) {
            throw response.fetchError
        }

        if (response.fetchResponse?.status === 410) {
            await this.deleteRestHook(hook?.id ?? '')
        }
    }

    private async deleteRestHook(hookId: Hook['id']): Promise<void> {
        await this.hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `DELETE FROM ee_hook WHERE id = $1`,
            [hookId],
            'deleteRestHook'
        )
    }

    @instrumented('cdpLegacyWebhookConsumer.processBatch')
    public async processBatch(events: PostIngestionEvent[]): Promise<{ backgroundTask: Promise<any> }> {
        await Promise.all(events.map((event) => this.processEvent(event)))

        return { backgroundTask: Promise.resolve() }
    }

    @instrumented('cdpLegacyWebhookConsumer.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<PostIngestionEvent[]> {
        return await this.runWithHeartbeat(async () => {
            const events: PostIngestionEvent[] = []

            await Promise.all(
                messages.map(async (message) => {
                    try {
                        const clickHouseEvent = parseJSON(message.value!.toString()) as RawClickHouseEvent

                        if (
                            !this.actionMatcher.hasWebhooks(clickHouseEvent.team_id) ||
                            !(await this.hub.teamManager.hasAvailableFeature(clickHouseEvent.team_id, 'zapier'))
                        ) {
                            // exit early if no webhooks nor resthooks
                            return
                        }

                        const eventWithoutGroups = convertToPostIngestionEvent(clickHouseEvent)
                        // This is very inefficient, we always pull group properties for all groups (up to 5) for this event
                        // from PG if a webhook is defined for this team.
                        // Instead we should be lazily loading group properties only when needed, but this is the fastest way to fix this consumer
                        // that will be deprecated in the near future by CDP/Hog
                        const event = await addGroupPropertiesToPostIngestionEvent(
                            eventWithoutGroups,
                            this.hub.groupTypeManager,
                            this.hub.teamManager,
                            this.hub.groupRepository
                        )

                        events.push(event)
                    } catch (e) {
                        logger.error('Error parsing message', e)
                        counterParseError.labels({ error: e.message }).inc()
                    }
                })
            )

            return events
        })
    }

    public async start(): Promise<void> {
        await super.start()
        await this.hub.actionManager.start()
        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('cdpLegacyWebhookConsumer.handleEachBatch', async () => {
                const events = await this._parseKafkaBatch(messages)
                return await this.processBatch(events)
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('💤', 'Stopping consumer...')
        await this.kafkaConsumer.disconnect()
        await this.hub.actionManager.stop()
        await super.stop()
        logger.info('💤', 'Consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
