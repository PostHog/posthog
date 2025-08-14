import { actions, afterMount, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { getAppContext } from 'lib/utils/getAppContext'

import { ProjectBasicType } from '~/types'

import type { organizationProjectsLogicType } from './organizationProjectsLogicType'

interface ProjectsCacheEntry {
    projects: ProjectBasicType[]
    updatedAt: number
}

interface ProjectsCacheByOrgId {
    [orgId: string]: ProjectsCacheEntry
}

function getCacheKey(): string {
    return 'ph_org_projects_by_org'
}

function loadProjectsFromLocalStorage(orgId: string | null): ProjectBasicType[] {
    if (!orgId) {
        return []
    }
    try {
        const raw = localStorage.getItem(getCacheKey())
        if (!raw) {
            return []
        }
        const parsed: ProjectsCacheByOrgId = JSON.parse(raw)
        return parsed[String(orgId)]?.projects ?? []
    } catch {
        return []
    }
}

function saveProjectsToLocalStorage(orgId: string, projects: ProjectBasicType[]): void {
    try {
        const raw = localStorage.getItem(getCacheKey())
        const parsed: ProjectsCacheByOrgId = raw ? JSON.parse(raw) : {}
        parsed[String(orgId)] = { projects, updatedAt: Date.now() }
        localStorage.setItem(getCacheKey(), JSON.stringify(parsed))
    } catch {
        // ignore
    }
}

export const organizationProjectsLogic = kea<organizationProjectsLogicType>([
    path(['scenes', 'organizationProjectsLogic']),
    actions({ refresh: true }),
    loaders(() => ({
        projects: [
            loadProjectsFromLocalStorage(getAppContext()?.current_team?.organization ?? null) as ProjectBasicType[],
            {
                loadProjects: async () => {
                    return (await api.loadPaginatedResults('api/projects', 1000)) as ProjectBasicType[]
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        loadProjectsSuccess: ({ projects }) => {
            const orgId = getAppContext()?.current_team?.organization ?? null
            if (orgId) {
                saveProjectsToLocalStorage(orgId, projects)
            }
        },
        refresh: async () => {
            await actions.loadProjects()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadProjects()
    }),
])
