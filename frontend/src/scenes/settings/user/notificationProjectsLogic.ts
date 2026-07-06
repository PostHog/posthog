import { connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { organizationsProjectsList } from '~/generated/core/api'
import type { ProjectBackwardCompatBasicApi } from '~/generated/core/api.schemas'
import type { OrganizationBasicType, UserType } from '~/types'

import type { notificationProjectsLogicType } from './notificationProjectsLogicType'

export type NotificationProject = {
    id: number
    name: string
    organizationId: string
    organizationName: string
}

export type NotificationProjectOrgGroup = {
    organizationId: string
    organizationName: string
    projects: NotificationProject[]
}

export const notificationProjectsLogic = kea<notificationProjectsLogicType>([
    path(['scenes', 'settings', 'user', 'notificationProjectsLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    loaders(({ values }) => ({
        projects: [
            [] as NotificationProject[],
            {
                loadProjects: async () => {
                    const organizations: OrganizationBasicType[] = values.user?.organizations ?? []
                    if (!organizations.length) {
                        return []
                    }

                    const perOrg = await Promise.all(
                        organizations.map(async (org): Promise<NotificationProject[]> => {
                            try {
                                const initial = await organizationsProjectsList(org.id, { limit: 100 })
                                const projects: ProjectBackwardCompatBasicApi[] = [
                                    ...initial.results,
                                    ...(await api.loadPaginatedResults<ProjectBackwardCompatBasicApi>(
                                        initial.next ?? null
                                    )),
                                ]
                                return projects.map((project) => ({
                                    id: project.id,
                                    name: project.name,
                                    organizationId: org.id,
                                    organizationName: org.name,
                                }))
                            } catch (e) {
                                console.warn(`Failed to load projects for organization ${org.id}`, e)
                                return []
                            }
                        })
                    )

                    return perOrg.flat()
                },
            },
        ],
    })),
    selectors({
        allProjectIds: [(s) => [s.projects], (projects: NotificationProject[]): number[] => projects.map((p) => p.id)],
        projectsByOrganization: [
            (s) => [s.projects],
            (projects: NotificationProject[]): NotificationProjectOrgGroup[] => {
                const groupsById = new Map<string, NotificationProjectOrgGroup>()
                for (const project of projects) {
                    let group = groupsById.get(project.organizationId)
                    if (!group) {
                        group = {
                            organizationId: project.organizationId,
                            organizationName: project.organizationName,
                            projects: [],
                        }
                        groupsById.set(project.organizationId, group)
                    }
                    group.projects.push(project)
                }
                for (const group of groupsById.values()) {
                    group.projects.sort((a, b) => a.name.localeCompare(b.name))
                }
                return [...groupsById.values()].sort((a, b) => a.organizationName.localeCompare(b.organizationName))
            },
        ],
    }),
    subscriptions(({ actions }) => ({
        // Fires on mount with the already-loaded user, and again if the user loads afterwards.
        user: (user: UserType | null, prevUser: UserType | null | undefined) => {
            if (user?.uuid && user.uuid !== prevUser?.uuid) {
                actions.loadProjects()
            }
        },
    })),
])
