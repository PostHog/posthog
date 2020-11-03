import { kea } from 'kea'
import api from 'lib/api'
import { projectLogicType } from 'types/scenes/projectLogicType'
import { ProjectType } from '~/types'

export const projectLogic = kea<projectLogicType<ProjectType>>({
    loaders: ({ values }) => ({
        currentProject: [
            null as ProjectType | null,
            {
                loadCurrentTeam: async () => {
                    try {
                        return await api.get('api/projects/@current')
                    } catch {
                        return null
                    }
                },
                // no API request in patch as that's handled in userLogic for now
                patchCurrentTeam: (patch: Partial<ProjectType>) => ({ ...values.currentProject, ...patch }),
                createTeam: async (name: string) => await api.create('api/projects/', { name }),
                resetToken: async () => await api.update('api/projects/@current/reset_token', {}),
            },
        ],
    }),
    listeners: {
        createTeamSuccess: () => {
            window.location.href = '/project/settings'
        },
    },
    events: ({ actions }) => ({
        afterMount: [actions.loadCurrentTeam],
    }),
})
