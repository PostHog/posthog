import * as schedule from 'node-schedule'

import { Action, Hook, PluginsServerConfig, RawAction, Team } from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { PubSub } from '../../utils/pubsub'
import { status } from '../../utils/status'

export type ActionMap = Record<Action['id'], Action>
type ActionCache = Record<Team['id'], ActionMap>

export class ActionManager {
    private started: boolean
    private ready: boolean
    private actionCache: ActionCache
    private pubSub: PubSub
    private refreshJob?: schedule.Job

    constructor(private postgres: PostgresRouter, private serverConfig: PluginsServerConfig) {
        this.started = false
        this.ready = false
        this.actionCache = {}

        this.pubSub = new PubSub(this.serverConfig, {
            'reload-action': async (message) => {
                const { actionId, teamId } = JSON.parse(message)
                await this.reloadAction(teamId, actionId)
            },
            'drop-action': (message) => {
                const { actionId, teamId } = JSON.parse(message)
                this.dropAction(teamId, actionId)
            },
        })
    }

    public async start(): Promise<void> {
        // TRICKY - when running with individual capabilities, this won't run twice but locally or as a complete service it will...
        if (this.started) {
            return
        }
        this.started = true
        await this.pubSub.start()
        await this.reloadAllActions()

        // every 5 minutes all ActionManager caches are reloaded for eventual consistency
        this.refreshJob = schedule.scheduleJob('*/5 * * * *', async () => {
            await this.reloadAllActions().catch((error) => {
                status.error('🍿', 'Error reloading actions:', error)
            })
        })
        this.ready = true
    }

    public async stop(): Promise<void> {
        if (this.refreshJob) {
            schedule.cancelJob(this.refreshJob)
        }

        await this.pubSub.stop()
    }

    public getTeamActions(teamId: Team['id']): ActionMap {
        if (!this.ready) {
            throw new Error('ActionManager is not ready! Run actionManager.start() before this')
        }
        return this.actionCache[teamId] || {}
    }

    public async reloadAllActions(): Promise<void> {
        this.actionCache = await fetchAllActionsGroupedByTeam(this.postgres)
        status.info('🍿', 'Fetched all actions from DB anew')
    }

    public async reloadAction(teamId: Team['id'], actionId: Action['id']): Promise<void> {
        const refetchedAction = await fetchAction(this.postgres, actionId)

        let wasCachedAlready = true
        if (!this.actionCache[teamId]) {
            wasCachedAlready = false
            this.actionCache[teamId] = {}
        } else if (!this.actionCache[teamId][actionId]) {
            wasCachedAlready = false
        }

        if (refetchedAction) {
            status.debug(
                '🍿',
                wasCachedAlready
                    ? `Refetched action ID ${actionId} (team ID ${teamId}) from DB`
                    : `Fetched new action ID ${actionId} (team ID ${teamId}) from DB`
            )
            this.actionCache[teamId][actionId] = refetchedAction
        } else if (wasCachedAlready) {
            delete this.actionCache[teamId][actionId]
        }
    }

    public dropAction(teamId: Team['id'], actionId: Action['id']): void {
        const wasCachedAlready = !!this.actionCache?.[teamId]?.[actionId]

        if (wasCachedAlready) {
            status.info('🍿', `Deleted action ID ${actionId} (team ID ${teamId}) from cache`)
            delete this.actionCache[teamId][actionId]
        } else {
            status.info(
                '🍿',
                `Tried to delete action ID ${actionId} (team ID ${teamId}) from cache, but it wasn't found in cache, so did nothing instead`
            )
        }
    }
}

export async function fetchAllActionsGroupedByTeam(
    client: PostgresRouter
): Promise<Record<Team['id'], Record<Action['id'], Action>>> {
    const restHooks = await fetchActionRestHooks(client)
    const restHookActionIds = restHooks.map(({ resource_id }) => resource_id)
    const additionalActionIds = [...restHookActionIds]

    const rawActions = (
        await client.query<RawAction>(
            PostgresUse.COMMON_READ,
            `
            SELECT
                id,
                team_id,
                name,
                description,
                created_at,
                created_by_id,
                deleted,
                post_to_slack,
                slack_message_format,
                is_calculating,
                updated_at,
                last_calculated_at,
                steps_json,
                bytecode,
                bytecode_error
            FROM posthog_action
            WHERE deleted = FALSE AND (post_to_slack OR id = ANY($1))
        `,
            [additionalActionIds],
            'fetchActions'
        )
    ).rows

    const actions: Record<Team['id'], Record<Action['id'], Action>> = {}
    for (const rawAction of rawActions) {
        if (!actions[rawAction.team_id]) {
            actions[rawAction.team_id] = {}
        }

        actions[rawAction.team_id][rawAction.id] = {
            ...rawAction,
            steps: rawAction.steps_json ?? [],
            hooks: [],
        }
    }
    for (const hook of restHooks) {
        if (hook.resource_id !== null && actions[hook.team_id]?.[hook.resource_id]) {
            actions[hook.team_id][hook.resource_id].hooks.push(hook)
        }
    }
    return actions
}

export async function fetchActionRestHooks(client: PostgresRouter, actionId?: Hook['resource_id']): Promise<Hook[]> {
    try {
        const { rows } = await client.query<Hook>(
            PostgresUse.COMMON_READ,
            `
            SELECT *
            FROM ee_hook
            WHERE event = 'action_performed'
            ${actionId !== undefined ? 'AND resource_id = $1' : ''}
            `,
            actionId !== undefined ? [actionId] : [],
            'fetchActionRestHooks'
        )
        return rows
    } catch (err) {
        // On FOSS this table does not exist - ignore errors
        if (err.message.includes('relation "ee_hook" does not exist')) {
            return []
        }

        throw err
    }
}

export async function fetchAction(client: PostgresRouter, id: Action['id']): Promise<Action | null> {
    const rawActions: RawAction[] = (
        await client.query(
            PostgresUse.COMMON_READ,
            `SELECT * FROM posthog_action WHERE id = $1 AND deleted = FALSE`,
            [id],
            'fetchActions'
        )
    ).rows
    if (!rawActions.length) {
        return null
    }

    const hooks = await fetchActionRestHooks(client, id)

    const action: Action = { ...rawActions[0], steps: rawActions[0].steps_json ?? [], hooks }
    return action.post_to_slack || action.hooks.length > 0 ? action : null
}
