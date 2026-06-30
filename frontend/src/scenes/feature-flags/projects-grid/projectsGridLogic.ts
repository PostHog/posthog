import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { OrganizationFeatureFlag, OrganizationFeatureFlagRow, OrganizationType } from '~/types'

import type { projectsGridLogicType } from './projectsGridLogicType'

export const PAGE_SIZE = 25

export interface LoadFlagsResult {
    offset: number
    search: string
    next: string | null
    results: OrganizationFeatureFlagRow[]
}

const storageKey = (teamId: number): string => `ff-projects-grid.picked-teams.${teamId}`

export const projectsGridLogic = kea<projectsGridLogicType>([
    path(['scenes', 'feature-flags', 'projects-grid', 'projectsGridLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], organizationLogic, ['currentOrganization']],
    })),
    actions({
        setSearch: (search: string) => ({ search }),
        loadMoreFlags: true,
        enqueueSiblingFetches: (keys: string[]) => ({ keys }),
        startSiblingFetch: (flagKey: string) => ({ flagKey }),
        siblingsLoaded: (flagKey: string, siblings: OrganizationFeatureFlag[]) => ({
            flagKey,
            siblings,
        }),
        siblingsFailed: (flagKey: string) => ({ flagKey }),
        setPickedTeamIds: (teamIds: number[]) => ({ teamIds }),
        resetPickedTeamIds: true,
    }),
    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
        flags: [
            [] as OrganizationFeatureFlagRow[],
            {
                loadFlagsPageSuccess: (state, { flagsPage }: { flagsPage: LoadFlagsResult }) =>
                    flagsPage.offset === 0 ? flagsPage.results : [...state, ...flagsPage.results],
                setSearch: () => [],
                setPickedTeamIds: () => [],
                resetPickedTeamIds: () => [],
            },
        ],
        flagsOffset: [
            0,
            {
                loadFlagsPageSuccess: (_, { flagsPage }: { flagsPage: LoadFlagsResult }) =>
                    flagsPage.offset + flagsPage.results.length,
                setSearch: () => 0,
                setPickedTeamIds: () => 0,
                resetPickedTeamIds: () => 0,
            },
        ],
        flagsHasMore: [
            true,
            {
                loadFlagsPageSuccess: (_, { flagsPage }: { flagsPage: LoadFlagsResult }) => flagsPage.next !== null,
                setSearch: () => true,
                setPickedTeamIds: () => true,
                resetPickedTeamIds: () => true,
            },
        ],
        siblingsByFlagKey: [
            {} as Record<string, OrganizationFeatureFlag[]>,
            {
                siblingsLoaded: (state, { flagKey, siblings }) => ({ ...state, [flagKey]: siblings }),
            },
        ],
        siblingsLoadingKeys: [
            [] as string[],
            {
                startSiblingFetch: (state, { flagKey }) => [...state, flagKey],
                siblingsLoaded: (state, { flagKey }) => state.filter((k) => k !== flagKey),
                siblingsFailed: (state, { flagKey }) => state.filter((k) => k !== flagKey),
                setSearch: () => [],
            },
        ],
        siblingQueue: [
            [] as string[],
            {
                enqueueSiblingFetches: (state, { keys }) => {
                    const dedup = keys.filter((k) => !state.includes(k))
                    return [...state, ...dedup]
                },
                startSiblingFetch: (state, { flagKey }) => state.filter((k) => k !== flagKey),
                setSearch: () => [],
            },
        ],
        pickedTeamIds: [
            [] as number[],
            {
                setPickedTeamIds: (_, { teamIds }) => teamIds,
                resetPickedTeamIds: () => [],
            },
        ],
    }),
    loaders(({ values }) => ({
        flagsPage: [
            null as LoadFlagsResult | null,
            {
                loadFlagsPage: async ({ offset, search }: { offset: number; search: string }, breakpoint) => {
                    const orgId = values.currentOrganization?.id
                    if (!orgId) {
                        return { offset, search, next: null, results: [] }
                    }
                    const response = await api.organizationFeatureFlags.keys(orgId, {
                        team_ids: values.visibleColumns,
                        search,
                        limit: PAGE_SIZE,
                        offset,
                    })
                    // Abort if a newer load (e.g. from a project-picker change) superseded this one.
                    breakpoint()
                    return { offset, search, next: response.next, results: response.results }
                },
            },
        ],
    })),
    selectors({
        visibleColumns: [
            (s) => [s.currentTeamId, s.pickedTeamIds],
            (currentTeamId, pickedTeamIds): number[] =>
                currentTeamId ? [currentTeamId, ...pickedTeamIds.filter((id) => id !== currentTeamId)] : pickedTeamIds,
        ],
        accessibleTeamIds: [
            (s) => [s.currentOrganization],
            (org: OrganizationType | null): Set<number> => new Set((org?.teams ?? []).map((t) => t.id)),
        ],
    }),
    listeners(({ actions, values }) => ({
        loadMoreFlags: () => {
            if (values.flagsHasMore && !values.flagsPageLoading) {
                actions.loadFlagsPage({ offset: values.flagsOffset, search: values.search })
            }
        },
        setSearch: async ({ search }, breakpoint) => {
            await breakpoint(300)
            actions.loadFlagsPage({ offset: 0, search })
        },
        loadFlagsPageSuccess: ({ flagsPage }: { flagsPage: LoadFlagsResult }) => {
            const newKeys = flagsPage.results.map((f) => f.key).filter((k) => !values.siblingsByFlagKey[k])
            if (newKeys.length) {
                actions.enqueueSiblingFetches(newKeys)
            }
        },
        enqueueSiblingFetches: async () => {
            await drainQueue(values, actions)
        },
        siblingsLoaded: async () => {
            await drainQueue(values, actions)
        },
        siblingsFailed: async () => {
            await drainQueue(values, actions)
        },
        setPickedTeamIds: ({ teamIds }) => {
            localStorage.setItem(storageKey(getCurrentTeamId()), JSON.stringify(teamIds))
            // Comparing more projects can surface flags that only exist in those projects, so reload rows.
            actions.loadFlagsPage({ offset: 0, search: values.search })
        },
        resetPickedTeamIds: () => {
            localStorage.removeItem(storageKey(getCurrentTeamId()))
            actions.loadFlagsPage({ offset: 0, search: values.search })
        },
    })),
    afterMount(({ actions }) => {
        const raw = localStorage.getItem(storageKey(getCurrentTeamId()))
        if (raw) {
            try {
                const parsed = JSON.parse(raw)
                if (Array.isArray(parsed) && parsed.every((x) => typeof x === 'number')) {
                    // setPickedTeamIds triggers the initial row load with the hydrated projects.
                    actions.setPickedTeamIds(parsed)
                    return
                }
            } catch {
                // ignore malformed entry
            }
        }
        actions.loadFlagsPage({ offset: 0, search: '' })
    }),
])

async function drainQueue(
    values: ReturnType<typeof projectsGridLogic.build>['values'],
    actions: ReturnType<typeof projectsGridLogic.build>['actions']
): Promise<void> {
    if (values.siblingsLoadingKeys.length > 0) {
        return
    }
    if (values.siblingQueue.length === 0) {
        return
    }

    const nextKey = values.siblingQueue[0]
    actions.startSiblingFetch(nextKey)

    try {
        const orgId = values.currentOrganization?.id
        if (!orgId) {
            actions.siblingsFailed(nextKey)
            return
        }
        // The wrapper is typed as `OrganizationFeatureFlags` (a legacy name), but the
        // endpoint actually returns a list of `OrganizationFeatureFlag`. Narrow once here.
        const siblings = (await api.organizationFeatureFlags.get(
            orgId,
            nextKey
        )) as unknown as OrganizationFeatureFlag[]
        actions.siblingsLoaded(nextKey, siblings)
    } catch {
        actions.siblingsFailed(nextKey)
    }
}
