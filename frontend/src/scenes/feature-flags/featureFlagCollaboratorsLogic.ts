import { kea } from 'kea'
import api from 'lib/api'
import { FeatureFlagPrivilegeLevel, FeatureFlagRestrictionLevel } from 'lib/constants'
import { teamMembersLogic } from 'scenes/project/Settings/teamMembersLogic'
import {
    UserType,
    FusedFeatureFlagCollaboratorType,
    UserBasicType,
    FeatureFlagCollaboratorType,
} from '~/types'
import { featureFlagLogic } from './featureFlagLogic'

import type { featureFlagCollaboratorsLogicType } from './featureFlagCollaboratorsLogicType'
import { teamLogic } from 'scenes/teamLogic'

export interface FeatureFlagCollaboratorsLogicProps {
    featureFlagId: number
}

export const featureFlagCollaboratorsLogic = kea<featureFlagCollaboratorsLogicType>({
    path: (key) => ['scenes', 'feature-flag', 'featureFlagCollaboratorsLogic', key],
    props: {} as FeatureFlagCollaboratorsLogicProps,
    key: (props) => props.featureFlagId,
    connect: (props: FeatureFlagCollaboratorsLogicProps) => ({
        values: [
            teamMembersLogic,
            ['admins', 'plainMembers', 'allMembers', 'allMembersLoading'],
            teamLogic,
            ['currentTeamId'],
            featureFlagLogic({ id: props.featureFlagId }),
            ['featureFlag'],
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
            [] as FeatureFlagCollaboratorType[],
            {
                loadExplicitCollaborators: async () => {
                    // const collaborators = await api.dashboards.collaborators.list(props.dashboardId)
                    const collaborators = await api.get(
                        `/api/projects/${values.currentTeamId}/feature_flags/${props.featureFlagId}/collaborators`
                    )
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
                                await api.create(`/api/projects/${values.currentTeamId}/feature_flags/${props.featureFlagId}/collaborators`, {
                                    user_uuid: userUuid,
                                    level: FeatureFlagPrivilegeLevel.CanEdit
                                })
                        )
                    )
                    const allCollaborators = [...explicitCollaborators, ...newCollaborators]
                    allCollaborators.sort((a, b) => a.user.first_name.localeCompare(b.user.first_name))
                    return allCollaborators
                },
                deleteExplicitCollaborator: async ({ userUuid }) => {
                    await api.dashboards.collaborators.delete(props.featureFlagId, userUuid)
                    return values.explicitCollaborators.filter((collaborator) => collaborator.user.uuid !== userUuid)
                },
            },
        ],
    }),
    selectors: {
        allCollaborators: [
            (s) => [s.explicitCollaborators, s.admins, s.allMembers, s.featureFlag],
            (explicitCollaborators, admins, allMembers, featureFlag): FusedFeatureFlagCollaboratorType[] => {
                const allCollaborators: FusedFeatureFlagCollaboratorType[] = []
                const dashboardCreatorUuid = featureFlag?.created_by?.uuid
                const baseCollaborators =
                    featureFlag?.effective_restriction_level === FeatureFlagRestrictionLevel.EveryoneInProjectCanEdit
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
                                    ? FeatureFlagPrivilegeLevel._Owner
                                    : explicitCollaborator.level,
                        }))
                )
                allCollaborators.push(
                    ...baseCollaborators.map((baseCollaborator) => ({
                        user: baseCollaborator.user,
                        level:
                            baseCollaborator.user.uuid === dashboardCreatorUuid
                                ? FeatureFlagPrivilegeLevel._Owner
                                : FeatureFlagPrivilegeLevel._ProjectAdmin,
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
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadExplicitCollaborators()
        },
    }),
})
