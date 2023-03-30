import { IngestionPersonData } from './../../types'
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
    Person,
} from '../../types'
import { DB } from '../../utils/db/db'
import { status } from '../../utils/status'
import { GraphileWorker } from '../../main/graphile-worker/graphile-worker'
import fetch from 'node-fetch'

export type AutomationMap = Record<string, any>
type AutomationCache = Record<Team['id'], AutomationMap>

export function applyEventToPayloadTemplate(payloadTemplate: any, event: any): any {
    function replaceTemplateRecursive(obj: any, path: string[]): any {
        if (typeof obj === 'string') {
            if (obj == '{event}') {
                return event
            }
            const matches = obj.match(/\{event\.[a-zA-Z0-9_.]+\}/g)
            if (matches) {
                for (const match of matches) {
                    const propertyPath = match.slice(7, -1).split('.')
                    let value = event
                    for (const key of propertyPath) {
                        if (value === undefined) {
                            break
                        }
                        value = value[key]
                    }
                    if (value !== undefined) {
                        if (obj === match) {
                            return value
                        } else {
                            obj = obj.replace(match, value)
                        }
                    }
                }
            }
            return obj
        } else if (Array.isArray(obj)) {
            return obj.map((item, index) => replaceTemplateRecursive(item, path.concat(index.toString())))
        } else if (typeof obj === 'object' && obj !== null) {
            const newObj: { [key: string]: any } = {}
            for (const key of Object.keys(obj)) {
                newObj[key] = replaceTemplateRecursive(obj[key], path.concat(key))
            }
            return newObj
        } else {
            return obj
        }
    }

    return replaceTemplateRecursive(payloadTemplate, [])
}

export class AutomationManager {
    private ready: boolean
    private automationCache: AutomationCache
    private interval: NodeJS.Timer | null

    constructor(
        private db: DB,
        private capabilities: PluginServerCapabilities,
        private actionManager: ActionManager,
        private actionMatcher: ActionMatcher
    ) {
        this.ready = false
        this.automationCache = {}
        this.interval = null
    }

    public async prepare(): Promise<void> {
        await this.reloadAllAutomations()
        this.interval = setInterval(async () => {
            await this.reloadAllAutomations()
        }, 1000 * 10) // TODO: make this smarter
        this.ready = true
    }

    private async getPersonFromDB(teamId: Team['id'], distinctId: string): Promise<Person | undefined> {
        const person = await this.db.fetchPerson(teamId, distinctId)
        if (!person) {
            return
        }
        return person
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
        const teamAutomations = this.getTeamAutomations(event.teamId) // TODO: This returns an action, needs to be turned into an automation type

        const person: IngestionPersonData | undefined = await this.getPersonFromDB(event.teamId, event.distinctId)
        event.person = person

        for (const automation of Object.values(teamAutomations)) {
            if (await this.actionMatcher.matchAutomation(automation, event, person)) {
                const job: EnqueuedAutomationJob = {
                    timestamp: Date.now(),
                    automation: automation,
                    event,
                    nodeId: automation.steps[1].id, // get the second node
                }

                await this.runAutomationJob(job, graphileWorker)
            }
        }
    }

    // Actually running the job that came from graphile
    public async runAutomationJob(job: EnqueuedAutomationJob, graphileWorker: GraphileWorker) {
        // 1. Find the node in the job.automation for job.nodeId
        const step = job.automation.steps.find((step: any) => step.id == job.nodeId) as any

        if (!step) {
            throw new Error('Could not find step with ID ' + job.nodeId)
        }
        // 2. run the corresponding action
        if (step.kind == 'WebhookDestination') {
            const response = await fetch(step.url, {
                method: 'POST',
                body: JSON.stringify(applyEventToPayloadTemplate(JSON.parse(step.payload), job.event)),
            })
            if (!response.ok) {
                throw new Error('Webhook failed')
            }
        }
        // 3. Enqueue the new job(s) with the next nodeIds
        // find the next node id from the edges
        const nextStep = job.automation.edges.find((edge: any) => edge.source == job.nodeId)?.target

        if (nextStep) {
            const newJob: EnqueuedAutomationJob = {
                ...job,
                nodeId: nextStep,
            }
            await graphileWorker.enqueue(JobName.AUTOMATION_JOB, newJob)
        } else {
            console.log('finished')
        }
        // Do the appropriate thing and then schedule the follow up job

        // DONT DO THIS
        // graphileWorker.enqueue(JobName.AUTOMATION_JOB, job)
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
