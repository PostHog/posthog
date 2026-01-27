import { Message } from 'node-rdkafka'

import { mutatePostIngestionEventWithElementsList } from '~/utils/event'
import { clickHouseTimestampSecondPrecisionToISO, clickHouseTimestampToISO } from '~/utils/utils'

import {
    Action,
    Hook,
    HookPayload,
    Hub,
    PostIngestionEvent,
    RawClickHouseEvent,
    RawKafkaEvent,
    Team,
} from '../../types'
import { PostgresUse } from '../../utils/db/postgres'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { counterParseError } from '../consumers/metrics'
import { ActionManager } from '../legacy-webhooks/action-manager'
import { ActionMatcher } from '../legacy-webhooks/action-matcher'
import { addGroupPropertiesToPostIngestionEvent } from '../legacy-webhooks/utils'
import { cdpTrackedFetch } from '../services/hog-executor.service'

/** Narrowed Hub type for LegacyWebhookService */
export type LegacyWebhookServiceHub = Pick<
    Hub,
    'postgres' | 'pubSub' | 'teamManager' | 'groupTypeManager' | 'groupRepository'
>

export class LegacyWebhookService {
    protected actionManager: ActionManager
    protected actionMatcher: ActionMatcher

    constructor(private hub: LegacyWebhookServiceHub) {
        this.actionManager = new ActionManager(hub.postgres, hub.pubSub)
        this.actionMatcher = new ActionMatcher(this.actionManager)
    }

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
        if (!hook.target) {
            return
        }

        const body: HookPayload = {
            hook: { id: hook.id, event: hook.event, target: hook.target },
            data: convertToHookPayload(event),
        }

        logger.debug('⚠️', `Firing webhook ${hook.target} for team ${team.id}`)

        const response = await cdpTrackedFetch({
            url: hook.target,
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
            await this.deleteRestHook(hook.id)
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

    public async processBatch(messages: Message[]): Promise<{ backgroundTask: Promise<any> }> {
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

        return { backgroundTask: Promise.all(events.map((event) => this.processEvent(event))) }
    }

    public async start(): Promise<void> {
        await this.actionManager.start()
    }

    public async stop(): Promise<void> {
        logger.info('💤', 'Stopping consumer...')
        await this.actionManager.stop()
    }
}

function convertToPostIngestionEvent(event: RawKafkaEvent): PostIngestionEvent {
    const properties = event.properties ? parseJSON(event.properties) : {}
    if (event.elements_chain) {
        properties['$elements_chain'] = event.elements_chain
    }

    return {
        eventUuid: event.uuid,
        event: event.event!,
        teamId: event.team_id,
        projectId: event.project_id,
        distinctId: event.distinct_id,
        properties,
        timestamp: clickHouseTimestampToISO(event.timestamp),
        elementsList: undefined,
        person_id: event.person_id,
        person_created_at: event.person_created_at
            ? clickHouseTimestampSecondPrecisionToISO(event.person_created_at)
            : null,
        person_properties: event.person_properties ? parseJSON(event.person_properties) : {},
    }
}

function convertToHookPayload(event: PostIngestionEvent): HookPayload['data'] {
    // It is only at this point that we need the elements list for the full event
    // NOTE: It is possible that nobody uses it in which case we could remove this for performance but
    // currently we have no way of being sure so we keep it in
    mutatePostIngestionEventWithElementsList(event)

    return {
        eventUuid: event.eventUuid,
        event: event.event,
        teamId: event.teamId,
        distinctId: event.distinctId,
        properties: event.properties,
        timestamp: event.timestamp,
        elementsList: event.elementsList,
        person: {
            uuid: event.person_id!,
            properties: event.person_properties,
            created_at: event.person_created_at,
        },
    }
}
