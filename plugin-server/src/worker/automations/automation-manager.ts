import { ActionManager } from '../ingestion/action-manager'
import { ActionMatcher } from '../ingestion/action-matcher'
import {
    Action,
    PluginServerCapabilities,
    Team,
    PostIngestionEvent,
    EnqueuedAutomationJob,
    AutomationJobState,
    JobName,
} from '../../types'
import { DB } from '../../utils/db/db'
import { status } from '../../utils/status'
import { GraphileWorker } from '../../main/graphile-worker/graphile-worker'
import fetch from 'node-fetch'

export type AutomationMap = Record<Action['id'], Action>
type AutomationCache = Record<Team['id'], AutomationMap>

export class AutomationManager {
    private ready: boolean
    private automationCache: AutomationCache

    constructor(
        private db: DB,
        private capabilities: PluginServerCapabilities,
        private actionManager: ActionManager,
        private actionMatcher: ActionMatcher
    ) {
        this.ready = false
        this.automationCache = {}
    }

    public async prepare(): Promise<void> {
        await this.reloadAllAutomations()
        this.ready = true
    }

    public getTeamAutomations(teamId: Team['id']): AutomationMap {
        if (!this.ready) {
            throw new Error('AutomationManager is not ready! Run AutomationManager.prepare() before this')
        }
        return this.automationCache[teamId] || {}
    }

    public async reloadAllAutomations(): Promise<void> {
        if (this.capabilities.processAutomationJobs) {
            this.automationCache = await this.db.fetchAllAutomationsGroupedByTeam() // TODO: This returns an action, needs to be turned into an automation type
            status.info('🍿', 'Fetched all automation from DB anew')
        }
    }

    public async startWithEvent(event: PostIngestionEvent, graphileWorker: GraphileWorker): Promise<void> {
        const teamAutomations = await this.getTeamAutomations(event.teamId) // TODO: This returns an action, needs to be turned into an automation type

        for (const automation of Object.values(teamAutomations)) {
            if (await this.actionMatcher.matchAutomation(automation, event)) {
                const webhookStep = automation.steps[1] as any
                // TODO: template the payload
                const response = await fetch(webhookStep.url, {
                    method: 'POST',
                    body: webhookStep.payload,
                })

                console.log('LUKE response', response)

                // const job: EnqueuedAutomationJob = {
                //     timestamp: Date.now(),
                //     automation: automation,
                //     event,
                //     state: AutomationJobState.SCHEDULED, // TODO: get rid of this
                //     nodeId: automation.steps[1].id, // get the next node
                // }
                // await new Promise((resolve) => setTimeout(resolve, 10)) // TODO: remove this

                // await this.runAutomationJob(job, graphileWorker)
            }
        }
    }

    // Actually running the job that came from graphile
    public async runAutomationJob(job: EnqueuedAutomationJob, graphileWorker: GraphileWorker) {
        // 1. Find the node in the job.automation for job.nodeId
        // 2. run the corresponding action
        // 3. Enqueue the new job(s) with the next nodeIds

        // Do the appropriate thing and then schedule the follow up job

        // DONT DO THIS
        // graphileWorker.enqueue(JobName.AUTOMATION_JOB, job)

        console.log(job)
    }

    // public async reloadAutomation(teamId: Team['id'], actionId: Action['id']): Promise<void> {
    //     if (!this.capabilities.processAutomationJobs) {
    //         return
    //     }

    //     const refetchedAction = await this.db.fetchAction(actionId)

    //     let wasCachedAlready = true
    //     if (!this.automationCache[teamId]) {
    //         wasCachedAlready = false
    //         this.automationCache[teamId] = {}
    //     } else if (!this.automationCache[teamId][actionId]) {
    //         wasCachedAlready = false
    //     }

    //     if (refetchedAction) {
    //         status.debug(
    //             '🍿',
    //             wasCachedAlready
    //                 ? `Refetched action ID ${actionId} (team ID ${teamId}) from DB`
    //                 : `Fetched new action ID ${actionId} (team ID ${teamId}) from DB`
    //         )
    //         this.automationCache[teamId][actionId] = refetchedAction
    //     } else if (wasCachedAlready) {
    //         delete this.automationCache[teamId][actionId]
    //     }
    // }

    // public dropAction(teamId: Team['id'], actionId: Action['id']): void {
    //     if (!this.capabilities.processAutomationJobs) {
    //         return
    //     }

    //     const wasCachedAlready = !!this.automationCache?.[teamId]?.[actionId]

    //     if (wasCachedAlready) {
    //         status.info('🍿', `Deleted action ID ${actionId} (team ID ${teamId}) from cache`)
    //         delete this.automationCache[teamId][actionId]
    //     } else {
    //         status.info(
    //             '🍿',
    //             `Tried to delete action ID ${actionId} (team ID ${teamId}) from cache, but it wasn't found in cache, so did nothing instead`
    //         )
    //     }
    // }
}
