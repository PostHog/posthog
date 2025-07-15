import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { ApiConfig } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { identifierToHuman, isUserLoggedIn } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { getAppContext } from 'lib/utils/getAppContext'

import { ProjectType } from '~/types'

import { organizationLogic } from './organizationLogic'
import type { projectLogicType } from './projectLogicType'
import { urls } from './urls'
import { userLogic } from './userLogic'

export const projectLogic = kea<projectLogicType>([
    path(['scenes', 'projectLogic']),
    actions({
        deleteProject: (project: ProjectType) => ({ project }),
        deleteProjectSuccess: true,
        deleteProjectFailure: true,
        moveProject: (project: ProjectType, organizationId: string) => ({ project, organizationId }),
    }),
    connect(() => ({
        actions: [
            userLogic,
            ['loadUser', 'switchTeam', 'updateCurrentOrganization'],
            organizationLogic,
            ['loadCurrentOrganization'],
        ],
    })),
    reducers({
        projectBeingDeleted: [
            null as ProjectType | null,
            {
                deleteProject: (_, { project }) => project,
                deleteProjectSuccess: () => null,
                deleteProjectFailure: () => null,
            },
        ],
    }),
    loaders(({ values, actions }) => ({
        currentProject: [
            null as ProjectType | null,
            {
                loadCurrentProject: async () => {
                    if (!isUserLoggedIn()) {
                        // If user is anonymous (i.e. viewing a shared dashboard logged out), don't load authenticated stuff
                        return null
                    }
                    try {
                        return await api.get('api/projects/@current')
                    } catch {
                        return values.currentProject
                    }
                },
                updateCurrentProject: async (payload: Partial<ProjectType>, breakpoint) => {
                    if (!values.currentProject) {
                        throw new Error('Current project has not been loaded yet, so it cannot be updated!')
                    }

                    const patchedProject = await api.update<ProjectType>(
                        `api/projects/${values.currentProject.id}`,
                        payload
                    )
                    breakpoint()

                    // We need to reload current org (which lists its projects) in organizationLogic AND in userLogic
                    actions.loadCurrentOrganization()
                    actions.loadUser()

                    Object.keys(payload).map((property) => {
                        eventUsageLogic.findMounted()?.actions?.reportProjectSettingChange(property, payload[property])
                    })

                    if (!window.location.pathname.match(/\/(onboarding|products)/)) {
                        /* Notify user the update was successful  */
                        const updatedAttribute = Object.keys(payload).length === 1 ? Object.keys(payload)[0] : null
                        const message = `${
                            updatedAttribute ? identifierToHuman(updatedAttribute) : 'Project'
                        } updated successfully!`
                        lemonToast.success(message)
                    }

                    return patchedProject
                },
                createProject: async ({ name }: { name: string }) => {
                    try {
                        return await api.create('api/projects/', { name })
                    } catch {
                        lemonToast.error('Failed to create project')
                        return values.currentProject
                    }
                },
            },
        ],

        projectBeingMoved: [
            null as ProjectType | null,
            {
                moveProject: async ({ project, organizationId }) => {
                    const res = await api.create<ProjectType>(`api/projects/${project.id}/change_organization`, {
                        organization_id: organizationId,
                    })

                    await api.update('api/users/@me/', { set_current_organization: organizationId })

                    return res
                },
            },
        ],
    })),
    selectors({
        currentProjectId: [(s) => [s.currentProject], (currentProject) => currentProject?.id || null],
    }),
    listeners(({ actions }) => ({
        loadCurrentProjectSuccess: ({ currentProject }) => {
            if (currentProject) {
                ApiConfig.setCurrentProjectId(currentProject.id)
            }
        },
        deleteProject: async ({ project }) => {
            try {
                await api.delete(`api/projects/${project.id}`)
                location.reload()
                actions.deleteProjectSuccess()
            } catch {
                actions.deleteProjectFailure()
            }
        },
        deleteProjectSuccess: () => {
            lemonToast.success('Project has been deleted')
        },
        createProjectSuccess: ({ currentProject }) => {
            if (currentProject) {
                actions.switchTeam(currentProject.id, urls.products())
            }
        },

        moveProjectSuccess: () => {
            lemonToast.success('Project has been moved. Redirecting...')
            window.location.reload()
        },
    })),
    afterMount(({ actions }) => {
        const appContext = getAppContext()
        const currentProject = appContext?.current_project

        if (currentProject) {
            // If app context is available (it should be practically always) we can immediately know currentProject
            actions.loadCurrentProjectSuccess(currentProject)
        } else {
            // If app context is not available, a traditional request is needed
            actions.loadCurrentProject()
        }
    }),
])
