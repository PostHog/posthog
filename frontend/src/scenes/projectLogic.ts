import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { identifierToHuman, isUserLoggedIn } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { getAppContext } from 'lib/utils/getAppContext'

import { ProjectType } from '~/types'

import type { projectLogicType } from './projectLogicType'
import { userLogic } from './userLogic'

export const projectLogic = kea<projectLogicType>([
    path(['scenes', 'projectLogic']),
    actions({
        deleteProject: (project: ProjectType) => ({ project }),
        deleteProjectSuccess: true,
        deleteProjectFailure: true,
    }),
    connect(() => ({
        actions: [userLogic, ['loadUser']],
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

                    const patchedProject = (await api.update(
                        `api/projects/${values.currentProject.id}`,
                        payload
                    )) as ProjectType
                    breakpoint()

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
                    return await api.create('api/projects/', { name })
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
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
