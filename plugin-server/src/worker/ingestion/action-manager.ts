import { Action, ActionStep, Hook, RawAction, Team } from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { status } from '../../utils/status'

export type ActionMap = Record<Action['id'], Action>
type ActionCache = Record<Team['id'], ActionMap>

export class ActionManager {
    private ready: boolean
    private postgres: PostgresRouter
    private actionCache: ActionCache

    constructor(postgres: PostgresRouter) {
        this.ready = false
        this.postgres = postgres
        this.actionCache = {}
    }

    public async prepare(): Promise<void> {
        await this.reloadAllActions()
        this.ready = true
    }

    public getTeamActions(teamId: Team['id']): ActionMap {
        if (!this.ready) {
            throw new Error('ActionManager is not ready! Run actionManager.prepare() before this')
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
                bytecode,
                bytecode_error
            FROM posthog_action
            WHERE deleted = FALSE AND (post_to_slack OR id = ANY($1))
        `,
            [restHookActionIds],
            'fetchActions'
        )
    ).rows

    const pluginIds: number[] = rawActions.map(({ id }) => id)
    const actionSteps: (ActionStep & { team_id: Team['id'] })[] = (
        await client.query(
            PostgresUse.COMMON_READ,
            `
                SELECT posthog_actionstep.*, posthog_action.team_id
                FROM posthog_actionstep JOIN posthog_action ON (posthog_action.id = posthog_actionstep.action_id)
                WHERE posthog_action.id = ANY($1)
            `,
            [pluginIds],
            'fetchActionSteps'
        )
    ).rows
    const actions: Record<Team['id'], Record<Action['id'], Action>> = {}
    for (const rawAction of rawActions) {
        if (!actions[rawAction.team_id]) {
            actions[rawAction.team_id] = {}
        }

        actions[rawAction.team_id][rawAction.id] = {
            ...rawAction,
            steps: [],
            hooks: [],
        }
    }
    for (const hook of restHooks) {
        if (hook.resource_id !== null && actions[hook.team_id]?.[hook.resource_id]) {
            actions[hook.team_id][hook.resource_id].hooks.push(hook)
        }
    }
    for (const actionStep of actionSteps) {
        if (actions[actionStep.team_id]?.[actionStep.action_id]) {
            actions[actionStep.team_id][actionStep.action_id].steps.push(actionStep)
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

    const [steps, hooks] = await Promise.all([
        client.query<ActionStep>(
            PostgresUse.COMMON_READ,
            `SELECT * FROM posthog_actionstep WHERE action_id = $1`,
            [id],
            'fetchActionSteps'
        ),
        fetchActionRestHooks(client, id),
    ])

    const action: Action = { ...rawActions[0], steps: steps.rows, hooks }
    return action.post_to_slack || action.hooks.length > 0 ? action : null
}
