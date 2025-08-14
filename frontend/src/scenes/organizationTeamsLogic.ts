import { actions, afterMount, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { getAppContext } from 'lib/utils/getAppContext'

import { TeamBasicType } from '~/types'

import type { organizationTeamsLogicType } from './organizationTeamsLogicType'

interface TeamsCacheEntry {
    teams: TeamBasicType[]
    updatedAt: number
}

interface TeamsCacheByOrgId {
    [orgId: string]: TeamsCacheEntry
}

function getCacheKey(): string {
    return 'ph_org_teams_by_org'
}

function loadTeamsFromLocalStorage(orgId: string | null): TeamBasicType[] {
    if (!orgId) {
        return []
    }
    try {
        const raw = localStorage.getItem(getCacheKey())
        if (!raw) {
            return []
        }
        const parsed: TeamsCacheByOrgId = JSON.parse(raw)
        return parsed[String(orgId)]?.teams ?? []
    } catch {
        return []
    }
}

function saveTeamsToLocalStorage(orgId: string, teams: TeamBasicType[]): void {
    try {
        const raw = localStorage.getItem(getCacheKey())
        const parsed: TeamsCacheByOrgId = raw ? JSON.parse(raw) : {}
        parsed[String(orgId)] = { teams, updatedAt: Date.now() }
        localStorage.setItem(getCacheKey(), JSON.stringify(parsed))
    } catch {
        // ignore
    }
}

export const organizationTeamsLogic = kea<organizationTeamsLogicType>([
    path(['scenes', 'organizationTeamsLogic']),
    actions({
        refresh: true,
    }),
    loaders(() => ({
        teams: [
            loadTeamsFromLocalStorage(getAppContext()?.current_team?.organization ?? null) as TeamBasicType[],
            {
                loadTeams: async () => {
                    // Prefer paginated list of environments (teams) over loading entire organization
                    return (await api.loadPaginatedResults('api/environments', 1000)) as TeamBasicType[]
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        loadTeamsSuccess: ({ teams }) => {
            const orgId = getAppContext()?.current_team?.organization ?? null
            if (orgId) {
                saveTeamsToLocalStorage(orgId, teams)
            }
        },
        refresh: async () => {
            await actions.loadTeams()
        },
    })),
    afterMount(({ actions }) => {
        // Refresh in the background to keep cache warm
        actions.loadTeams()
    }),
])
