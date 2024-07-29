import { Team } from '../types'
import { delay } from '../utils/utils'
import { GroupsManager } from './groups-manager'
import { GroupType, HogFunctionFilterGlobals, HogFunctionInvocationGlobals } from './types'

export type GroupsMap = Record<string, GroupType>
export type GroupsCache = Record<Team['id'], GroupsMap>

/**
 * Special class to help with managing the globals that are sent to a hog function or filter
 *
 * It is needed for a few reasons:
 * 1. We want to minimize DB calls and cache as much as possible
 * 2. We want to minimize the payload sent to a hog function as this means less data needs to be serialized and stored
 */
export class HogFunctionGlobalsManager {
    private groupsBuffer?: {
        promise: Promise<any>
        items: HogFunctionInvocationGlobals[]
    }

    constructor(private groupsManager: GroupsManager) {}

    private async loadGroups(context: HogFunctionInvocationGlobals): Promise<HogFunctionInvocationGlobals['groups']> {
        // Load groups efficiently via a buffered call - this is to avoid making multiple calls to the DB
        if (!this.groupsBuffer) {
            this.groupsBuffer = {
                promise: delay(100).then(() => {
                    const items = this.groupsBuffer?.items || []
                    this.groupsBuffer = undefined
                    return this.groupsManager.enrichGroups(items)
                }),
                items: [],
            }
        }

        this.groupsBuffer.items.push(context)
        await this.groupsBuffer.promise

        return context.groups
    }

    public async loadGlobals(
        context: HogFunctionInvocationGlobals,
        globalsRequired: Set<string>
    ): Promise<Partial<HogFunctionInvocationGlobals>> {
        const obj: Partial<HogFunctionInvocationGlobals> = {}
        const loaders: Promise<any>[] = []

        for (const key in globalsRequired) {
            obj[key] = context[key]

            // For certain keys we need to load additional data if not present such as groups
            if (key === 'groups' && !context[key]) {
                loaders.push(
                    this.loadGroups(context).then((groups) => {
                        obj[key] = groups
                    })
                )
            }
        }

        await Promise.all(loaders)

        return obj
    }

    public async loadFiltersGlobals(
        context: HogFunctionInvocationGlobals,
        globalsRequired: Set<string>
    ): Promise<Partial<HogFunctionFilterGlobals>> {
        const groupsNeeded = Array.from(globalsRequired).some((x) => x.startsWith('group_'))
        let groups: HogFunctionInvocationGlobals['groups'] = {}

        if (!groupsNeeded) {
            const loaded = await this.loadGlobals(context, new Set(['groups']))
            groups = loaded.groups || {}
        }

        const eventGroups: Record<string, any> = {}

        for (const [_groupType, group] of Object.entries(groups || {})) {
            eventGroups[`group_${group.index}`] = {
                properties: group.properties,
            }
        }

        const payload: HogFunctionFilterGlobals = {
            event: context.event.name,
            elements_chain: context.event.properties['$elements_chain'],
            timestamp: context.event.timestamp,
            properties: context.event.properties,
            person: context.person ? { properties: context.person.properties } : undefined,
            ...groups,
        }

        const obj: Partial<HogFunctionFilterGlobals> = {}

        for (const key in payload) {
            if (globalsRequired.has(key)) {
                obj[key] = payload[key]
            }
        }

        return obj
    }
}
