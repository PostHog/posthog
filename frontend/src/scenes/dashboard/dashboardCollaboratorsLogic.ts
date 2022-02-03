import { kea } from 'kea'
import api from 'lib/api'
import { DashboardType, DashboardCollaboratorType, UserType } from '~/types'
import { dashboardCollaboratorsLogicType } from './dashboardCollaboratorsLogicType'

export const dashboardCollaboratorsLogic = kea<dashboardCollaboratorsLogicType>({
    path: (key) => ['scenes', 'dashboard', 'dashboardCollaboratorsLogic', key],
    props: {} as {
        dashboardId: DashboardType['id']
    },
    key: (props) => props.dashboardId,
    actions: () => ({
        deleteExplicitCollaborator: (userUuid: UserType['uuid']) => ({ userUuid }),
    }),
    loaders: ({ values, props }) => ({
        explicitCollaborators: [
            [] as DashboardCollaboratorType[],
            {
                loadExplicitCollaborators: async () => {
                    return await api.dashboards.collaborators.list(props.dashboardId)
                },
                deleteExplicitCollaborator: async ({ userUuid }) => {
                    await api.dashboards.collaborators.delete(props.dashboardId, userUuid)
                    return values.explicitCollaborators.filter((collaborator) => collaborator.user.uuid !== userUuid)
                },
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadExplicitCollaborators()
        },
    }),
})
