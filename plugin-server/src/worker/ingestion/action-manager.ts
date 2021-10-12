import { Action, Team } from '../../types'
import { DB } from '../../utils/db/db'
import { status } from '../../utils/status'

export type ActionMap = Record<Action['id'], Action>
type ActionCache = Record<Team['id'], ActionMap>

export class ActionManager {
    private ready: boolean
    private db: DB
    private actionCache: ActionCache

    constructor(db: DB) {
        this.ready = false
        this.db = db
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
        this.actionCache = await this.db.fetchAllActionsGroupedByTeam()
        status.info('🍿', 'Fetched all actions from DB anew')
    }

    public async reloadAction(teamId: Team['id'], actionId: Action['id']): Promise<void> {
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
            status.info(
                '🍿',
                `Tried to fetch action ID ${actionId} (team ID ${teamId}) from DB, but it wasn't found in DB, so deleted from cache instead`
            )
            delete this.actionCache[teamId][actionId]
        } else {
            status.info(
                '🍿',
                `Tried to fetch action ID ${actionId} (team ID ${teamId}) from DB, but it wasn't found in DB or cache, so did nothing instead`
            )
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
