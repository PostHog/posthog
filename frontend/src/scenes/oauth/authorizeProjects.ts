import posthog from 'posthog-js'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import type { TeamBasicType } from '~/types'

export type AuthorizeScreen = 'oauth' | 'agentic'

// pinned: analytics event name, renaming breaks dashboards
const PROJECTS_LOADED_EVENT = 'authorize projects loaded'

/**
 * Projects the person can authorize, for both consent screens.
 * They share this loader so the two screens cannot drift apart again.
 */
export async function loadAuthorizeProjects(screen: AuthorizeScreen): Promise<TeamBasicType[]> {
    const organizations = userLogic.values.user?.organizations ?? []
    const startedAt = performance.now()

    const capture = (success: boolean, teamCount: number): void => {
        posthog.capture(PROJECTS_LOADED_EVENT, {
            screen,
            success,
            duration_ms: Math.round(performance.now() - startedAt),
            organization_count: organizations.length,
            team_count: teamCount,
        })
    }

    try {
        const teams = organizations.length
            ? (
                  await Promise.all(
                      organizations.map((organization) =>
                          api.loadPaginatedResults<TeamBasicType>(`api/organizations/${organization.id}/projects`)
                      )
                  )
              ).flat()
            : await api.loadPaginatedResults<TeamBasicType>('api/projects')
        capture(true, teams.length)
        return teams
    } catch (error) {
        capture(false, 0)
        throw error
    }
}
