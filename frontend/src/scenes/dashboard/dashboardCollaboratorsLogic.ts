import { actions, connect, events, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { DashboardPrivilegeLevel, DashboardRestrictionLevel, OrganizationMembershipLevel } from 'lib/constants'
import { membersLogic } from 'scenes/organization/membersLogic'

import {
    DashboardCollaboratorType,
    DashboardType,
    FusedDashboardCollaboratorType,
    FusedTeamMemberType,
    UserBasicType,
    UserType,
} from '~/types'

import type { dashboardCollaboratorsLogicType } from './dashboardCollaboratorsLogicType'
import { dashboardLogic } from './dashboardLogic'

export interface DashboardCollaboratorsLogicProps {
    dashboardId: DashboardType['id']
}

export const dashboardCollaboratorsLogic = kea<dashboardCollaboratorsLogicType>([
    props({} as DashboardCollaboratorsLogicProps),
    key((props) => props.dashboardId),
    path((key) => ['scenes', 'dashboard', 'dashboardCollaboratorsLogic', key]),
    connect((props: DashboardCollaboratorsLogicProps) => ({
        values: [membersLogic, ['members', 'membersLoading'], dashboardLogic({ id: props.dashboardId }), ['dashboard']],
    })),
    actions({
        deleteExplicitCollaborator: (userUuid: UserType['uuid']) => ({ userUuid }),
        setExplicitCollaboratorsToBeAdded: (userUuids: string[]) => ({ userUuids }),
        addExplicitCollaborators: true,
    }),
    loaders(({ values, props, actions }) => ({
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
    })),
    reducers({
        explicitCollaboratorsToBeAdded: [
            [] as string[],
            {
                setExplicitCollaboratorsToBeAdded: (_, { userUuids }) => userUuids,
            },
        ],
    }),
    selectors({
        // Create the missing selectors that teamMembersLogic used to provide
        allMembers: [
            (s) => [s.members],
            (members): FusedTeamMemberType[] =>
                (members || []).map((member) => ({
                    ...member,
                    explicit_team_level: null,
                    organization_level: member.level,
                })),
        ],
        admins: [
            (s) => [s.allMembers],
            (allMembers: FusedTeamMemberType[]): FusedTeamMemberType[] =>
                allMembers.filter(({ level }) => level >= OrganizationMembershipLevel.Admin),
        ],
        plainMembers: [
            (s) => [s.allMembers],
            (allMembers: FusedTeamMemberType[]): FusedTeamMemberType[] =>
                allMembers.filter(({ level }) => level < OrganizationMembershipLevel.Admin),
        ],
        allMembersLoading: [(s) => [s.membersLoading], (membersLoading): boolean => membersLoading],
        allCollaborators: [
            (s) => [s.explicitCollaborators, s.admins, s.allMembers, s.dashboard],
            (explicitCollaborators, admins, allMembers, dashboard): FusedDashboardCollaboratorType[] => {
                const allCollaborators: FusedDashboardCollaboratorType[] = []
                const dashboardCreatorUuid = dashboard?.created_by?.uuid
                const baseCollaborators =
                    dashboard?.effective_restriction_level === DashboardRestrictionLevel.EveryoneInProjectCanEdit
                        ? allMembers
                        : admins
                allCollaborators.push(
                    ...explicitCollaborators
                        .filter(
                            (collaborator) =>
                                !baseCollaborators.find(
                                    (baseCollaborator) => baseCollaborator.user.uuid === collaborator.user.uuid
                                )
                        )
                        .map((explicitCollaborator) => ({
                            ...explicitCollaborator,
                            level:
                                explicitCollaborator.user.uuid === dashboardCreatorUuid
                                    ? DashboardPrivilegeLevel._Owner
                                    : explicitCollaborator.level,
                        }))
                )
                allCollaborators.push(
                    ...baseCollaborators.map((baseCollaborator) => ({
                        user: baseCollaborator.user,
                        level:
                            baseCollaborator.user.uuid === dashboardCreatorUuid
                                ? DashboardPrivilegeLevel._Owner
                                : DashboardPrivilegeLevel._ProjectAdmin,
                    }))
                )
                allCollaborators.sort((a, b) =>
                    a.level === b.level ? a.user.first_name.localeCompare(b.user.first_name) : b.level - a.level
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
                addableMembers.sort((a, b) => a.first_name.localeCompare(b.first_name))
                return addableMembers
            },
        ],
        addableMembersLoading: [
            (s) => [s.explicitCollaboratorsLoading, s.allMembersLoading],
            (explicitCollaboratorsLoading, allMembersLoading): boolean =>
                explicitCollaboratorsLoading || allMembersLoading,
        ],
    }),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadExplicitCollaborators()
        },
    })),
])
