import { kea } from 'kea'
import api from 'lib/api'
import { DashboardPrivilegeLevel } from 'lib/constants'
import { teamMembersLogic } from 'scenes/project/Settings/teamMembersLogic'
import {
    DashboardType,
    DashboardCollaboratorType,
    UserType,
    FusedDashboardCollaboratorType,
    UserBasicType,
} from '~/types'
import { dashboardCollaboratorsLogicType } from './dashboardCollaboratorsLogicType'
import { dashboardLogic } from './dashboardLogic'

export interface DashboardCollaboratorsLogicProps {
    dashboardId: DashboardType['id']
}

export const dashboardCollaboratorsLogic = kea<dashboardCollaboratorsLogicType<DashboardCollaboratorsLogicProps>>({
    path: (key) => ['scenes', 'dashboard', 'dashboardCollaboratorsLogic', key],
    props: {} as DashboardCollaboratorsLogicProps,
    key: (props) => props.dashboardId,
    connect: (props: DashboardCollaboratorsLogicProps) => ({
        values: [
            teamMembersLogic,
            ['admins', 'plainMembers', 'allMembersLoading'],
            dashboardLogic({ id: props.dashboardId }),
            ['dashboard'],
        ],
    }),
    actions: {
        deleteExplicitCollaborator: (userUuid: UserType['uuid']) => ({ userUuid }),
        setExplicitCollaboratorsToBeAdded: (userUuids: string[]) => ({ userUuids }),
        addExplicitCollaborators: true,
    },
    reducers: {
        explicitCollaboratorsToBeAdded: [
            [] as string[],
            {
                setExplicitCollaboratorsToBeAdded: (_, { userUuids }) => userUuids,
            },
        ],
    },
    loaders: ({ values, props, actions }) => ({
        explicitCollaborators: [
            [] as DashboardCollaboratorType[],
            {
                loadExplicitCollaborators: async () => {
                    const collaborators = await api.dashboards.collaborators.list(props.dashboardId)
                    collaborators.sort((a, b) => a.user.first_name.localeCompare(b.user.first_name))
                    return collaborators
                },
                addExplicitCollaborators: async () => {
                    const { explicitCollaboratorsToBeAdded, explicitCollaborators } = values
                    actions.setExplicitCollaboratorsToBeAdded([])
                    const newCollaborators = await Promise.all(
                        explicitCollaboratorsToBeAdded.map(
                            async (userUuid) =>
                                // Currently only CanEdit can be explicitly granted, as CanView is the base level
                                await api.dashboards.collaborators.create(
                                    props.dashboardId,
                                    userUuid,
                                    DashboardPrivilegeLevel.CanEdit
                                )
                        )
                    )
                    const allCollaborators = [...explicitCollaborators, ...newCollaborators]
                    allCollaborators.sort((a, b) => a.user.first_name.localeCompare(b.user.first_name))
                    return allCollaborators
                },
                deleteExplicitCollaborator: async ({ userUuid }) => {
                    await api.dashboards.collaborators.delete(props.dashboardId, userUuid)
                    return values.explicitCollaborators.filter((collaborator) => collaborator.user.uuid !== userUuid)
                },
            },
        ],
    }),
    selectors: {
        allCollaborators: [
            (s) => [s.explicitCollaborators, s.admins, s.dashboard],
            (explicitCollaborators, admins, dashboard): FusedDashboardCollaboratorType[] => {
                const allCollaborators: FusedDashboardCollaboratorType[] = []
                let dashboardCreatorUuid: UserBasicType['uuid'] | undefined
                if (dashboard?.created_by) {
                    dashboardCreatorUuid = dashboard.created_by.uuid
                    allCollaborators.push({
                        user: dashboard.created_by,
                        level: 'owner',
                    })
                }
                allCollaborators.push(
                    ...explicitCollaborators.filter(
                        (collaborator) =>
                            !admins.find((admin) => admin.user.uuid === collaborator.user.uuid) &&
                            collaborator.user.uuid !== dashboardCreatorUuid
                    )
                )
                allCollaborators.push(
                    ...admins
                        .filter((admin) => admin.user.uuid !== dashboardCreatorUuid)
                        .map(
                            (admin) =>
                                ({
                                    user: admin.user,
                                    level: 'project-admin',
                                } as FusedDashboardCollaboratorType)
                        )
                )
                return allCollaborators
            },
        ],
        addableMembers: [
            (s) => [s.allCollaborators, s.plainMembers],
            (allCollaborators, plainMembers): UserBasicType[] => {
                const addableMembers: UserBasicType[] = []
                for (const plainMember of plainMembers) {
                    if (!allCollaborators.some((collaborator) => collaborator.user.uuid === plainMember.user.uuid)) {
                        addableMembers.push(plainMember.user)
                    }
                }
                return addableMembers
            },
        ],
        addableMembersLoading: [
            (s) => [s.explicitCollaboratorsLoading, s.allMembersLoading],
            (explicitCollaboratorsLoading, allMembersLoading): boolean =>
                explicitCollaboratorsLoading || allMembersLoading,
        ],
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadExplicitCollaborators()
        },
    }),
})
