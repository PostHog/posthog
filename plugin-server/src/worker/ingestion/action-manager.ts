import { Action, PluginServerCapabilities, Team } from '../../types'
import { DB } from '../../utils/db/db'
import { status } from '../../utils/status'

export type ActionMap = Record<Action['id'], Action>
type ActionCache = Record<Team['id'], ActionMap>

export class ActionManager {
    private ready: boolean
    private db: DB
    private actionCache: ActionCache
    private capabilities: PluginServerCapabilities

    constructor(db: DB, capabilities: PluginServerCapabilities) {
        this.ready = false
        this.db = db
        this.capabilities = capabilities
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
        if (this.capabilities.processAsyncHandlers) {
            this.actionCache = await this.db.fetchAllActionsGroupedByTeam()
            status.info('🍿', 'Fetched all actions from DB anew')
        }
    }

    public async reloadAction(teamId: Team['id'], actionId: Action['id']): Promise<void> {
        if (!this.capabilities.processAsyncHandlers) {
            return
        }

        const refetchedAction = await this.db.fetchAction(actionId)

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
        if (!this.capabilities.processAsyncHandlers) {
            return
        }

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
