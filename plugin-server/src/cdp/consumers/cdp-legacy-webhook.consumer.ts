import { Message } from 'node-rdkafka'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { KafkaConsumer } from '~/kafka/consumer'
import { addGroupPropertiesToPostIngestionEvent } from '~/main/ingestion-queues/batch-processing/each-batch-webhooks'

import {
    Action,
    GroupTypeIndex,
    GroupTypeToColumnIndex,
    HealthCheckResult,
    Hook,
    HookPayload,
    Hub,
    ISOTimestamp,
    PostIngestionEvent,
    ProjectId,
    RawClickHouseEvent,
    Team,
    TeamId,
} from '../../types'
import { PostgresUse } from '../../utils/db/postgres'
import { convertToHookPayload, convertToPostIngestionEvent } from '../../utils/event'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { cdpTrackedFetch } from '../services/hog-executor.service'
import { HogFunctionInvocationGlobals } from '../types'
import { CdpConsumerBase } from './cdp-base.consumer'
import { counterParseError } from './metrics'

/**
 * This consumer processes webhook events from the legacy webhooks system.
 * It uses the new node-rdkafka consumer tech while maintaining compatibility
 * with the existing webhook processing logic but using inline safe fetch.
 */

export class CdpLegacyWebhookConsumer extends CdpConsumerBase {
    protected name = 'CdpLegacyWebhookConsumer'
    protected promiseScheduler = new PromiseScheduler()
    protected kafkaConsumer: KafkaConsumer

    constructor(hub: Hub) {
        super(hub)

        this.kafkaConsumer = new KafkaConsumer({
            groupId: hub.CDP_LEGACY_WEBHOOK_CONSUMER_GROUP_ID,
            topic: hub.CDP_LEGACY_WEBHOOK_CONSUMER_TOPIC,
        })

        logger.info('🔁', `CdpLegacyWebhookConsumer setup`)
    }

    @instrumented('cdpLegacyWebhookConsumer.processEvent')
    public async processEvent(event: PostIngestionEvent) {
        const actionMatches = this.hub.actionMatcher.match(event)
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

    private async addGroupPropertiesToEvent(globals: HogFunctionInvocationGlobals): Promise<PostIngestionEvent> {
        const eventWithoutGroups: PostIngestionEvent = {
            eventUuid: globals.event.uuid,
            event: globals.event.event,
            teamId: globals.project.id,
            distinctId: globals.event.distinct_id,
            properties: globals.event.properties,
            timestamp: globals.event.timestamp as ISOTimestamp,
            projectId: globals.project.id as ProjectId,
            person_created_at: null,
            person_properties: {},
            person_id: undefined,
        }

        let groupTypes: GroupTypeToColumnIndex | null = null
        if (await this.hub.teamManager.hasAvailableFeature(globals.project.id, 'group_analytics')) {
            groupTypes = await this.hub.groupTypeManager.fetchGroupTypes(globals.project.id as ProjectId)
        }

        let groups: PostIngestionEvent['groups'] = undefined
        if (groupTypes) {
            groups = {}

            for (const [groupType, columnIndex] of Object.entries(groupTypes)) {
                const $groups = globals.event.properties['$groups']
                const groupKey = (
                    $groups && typeof $groups === 'object' && !Array.isArray($groups)
                        ? ($groups as Record<string, string>)[groupType]
                        : undefined
                ) as string | undefined

                if (!groupKey) {
                    continue
                }

                const group = await this.hub.groupRepository.fetchGroup(
                    globals.project.id as TeamId,
                    columnIndex as GroupTypeIndex,
                    groupKey,
                    { useReadReplica: true }
                )

                const groupProperties = group ? group.group_properties : {}

                if (groupKey && groupProperties) {
                    groups[groupType] = {
                        index: columnIndex,
                        key: groupKey,
                        type: groupType,
                        properties: groupProperties,
                    }
                }
            }
        }

        return {
            ...eventWithoutGroups,
            groups,
        }
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
                            !this.hub.actionMatcher.hasWebhooks(clickHouseEvent.team_id) &&
                            (await this.hub.teamManager.hasAvailableFeature(clickHouseEvent.team_id, 'zapier'))
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
        await super.stop()
        logger.info('💤', 'Consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
