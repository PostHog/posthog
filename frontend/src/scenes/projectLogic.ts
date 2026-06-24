import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api, { ApiConfig } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { isUserLoggedIn } from 'lib/utils/getAppContext'
import { getAppContext } from 'lib/utils/getAppContext'
import { identifierToHuman } from 'lib/utils/strings'

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
        guardPendingDeletion: (pathname: string, isPendingDeletion: boolean | null | undefined) => ({
            pathname,
            isPendingDeletion,
        }),
        moveProject: (project: ProjectType, organizationId: string) => ({ project, organizationId }),
    }),
    connect(() => ({
        actions: [
            userLogic,
            ['loadUser', 'switchTeam', 'updateCurrentOrganization'],
            organizationLogic,
            ['loadCurrentOrganization'],
        ],
        values: [userLogic, ['otherOrganizations']],
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
                    // Let failures (e.g. a 403 for non-admins) propagate: kea-loaders surfaces the API
                    // error toast and clears the loading state, and createProjectSuccess never fires — so we
                    // don't switch into a project that wasn't created or leave the modal stuck open.
                    return await api.create('api/projects/', { name })
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
        moveProjectDisabledReason: [
            (s) => [s.otherOrganizations],
            (otherOrganizations) =>
                otherOrganizations.length === 0
                    ? "You can't move the project because you aren't a member of another organization"
                    : null,
        ],
    }),
    listeners(({ actions, values }) => ({
        loadCurrentProjectSuccess: ({ currentProject }) => {
            if (currentProject) {
                ApiConfig.setCurrentProjectId(currentProject.id)
            }
            // Lock the project out once deletion has been initiated (covers full page loads / reloads)
            actions.guardPendingDeletion(router.values.location.pathname, currentProject?.is_pending_deletion)
        },
        locationChanged: ({ pathname }) => {
            actions.guardPendingDeletion(pathname, values.currentProject?.is_pending_deletion)
        },
        guardPendingDeletion: ({ pathname, isPendingDeletion }) => {
            // projectBased scenes are served under a /project/:id prefix, so match the lockout path by suffix.
            const onLockoutScreen = pathname.endsWith(urls.projectPendingDeletion())
            if (isPendingDeletion && !onLockoutScreen) {
                router.actions.replace(urls.projectPendingDeletion())
            } else if (!isPendingDeletion && onLockoutScreen) {
                // Reached the lockout screen for a project that isn't being deleted (e.g. switched projects) — send home
                router.actions.replace(urls.projectHomepage())
            }
        },
        deleteProject: async ({ project }) => {
            try {
                await api.delete(`api/projects/${project.id}`)
                actions.deleteProjectSuccess()
            } catch (e) {
                const apiError = e as Record<string, any>
                lemonToast.error(apiError.detail || 'Failed to delete project. Please try again.')
                actions.deleteProjectFailure()
            }
        },
        deleteProjectSuccess: () => {
            lemonToast.success('Project deletion has been initiated')
            // Full reload so the bootstrap context carries is_pending_deletion and lands on the lockout screen
            window.location.href = urls.projectPendingDeletion()
        },
        createProjectSuccess: ({ currentProject }) => {
            if (currentProject) {
                actions.switchTeam(currentProject.id, urls.projectHomepage())
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
