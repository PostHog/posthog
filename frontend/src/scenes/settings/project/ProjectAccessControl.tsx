import { IconCrown, IconLeave, IconLock, IconUnlock } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSelectOption, LemonSnack, LemonSwitch, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { OrganizationMembershipLevel, TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDetailedTime } from 'lib/utils'
import {
    getReasonForAccessLevelChangeProhibition,
    membershipLevelToName,
    teamMembershipLevelIntegers,
} from 'lib/utils/permissioning'
import { organizationLogic } from 'scenes/organizationLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AccessControlObject } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlObject'
import { AvailableFeature, FusedTeamMemberType } from '~/types'

import { AddMembersModalWithButton } from './AddMembersModal'
import { MINIMUM_IMPLICIT_ACCESS_LEVEL, teamMembersLogic } from './teamMembersLogic'

function LevelComponent(member: FusedTeamMemberType): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { changeUserAccessLevel } = useActions(teamMembersLogic)

    const myMembershipLevel = isAuthenticatedTeam(currentTeam) ? currentTeam.effective_membership_level : null

    if (!user) {
        return null
    }

    const isImplicit = member.organization_level >= OrganizationMembershipLevel.Admin
    const levelName = membershipLevelToName.get(member.level) ?? `unknown (${member.level})`

    const allowedLevels = teamMembershipLevelIntegers.filter(
        (listLevel) => !getReasonForAccessLevelChangeProhibition(myMembershipLevel, user, member, listLevel)
    )

    const possibleOptions = member.explicit_team_level
        ? allowedLevels.concat([member.explicit_team_level])
        : allowedLevels

    const disallowedReason = isImplicit
        ? `This user is a member of the project implicitly due to being an organization ${levelName}.`
        : getReasonForAccessLevelChangeProhibition(myMembershipLevel, user, member, allowedLevels)

    return disallowedReason ? (
        <Tooltip title={disallowedReason}>
            <LemonSnack className="capitalize">
                {member.level === OrganizationMembershipLevel.Owner && <IconCrown className="mr-2" />}
                {levelName}
            </LemonSnack>
        </Tooltip>
    ) : (
        <LemonSelect
            dropdownMatchSelectWidth={false}
            onChange={(listLevel) => {
                if (listLevel !== null) {
                    changeUserAccessLevel(member.user, listLevel)
                }
            }}
            options={possibleOptions.map(
                (listLevel) =>
                    ({
                        value: listLevel,
                        disabled: listLevel === member.explicit_team_level,
                        label:
                            listLevel > member.level
                                ? membershipLevelToName.get(listLevel)
                                : membershipLevelToName.get(listLevel),
                    } as LemonSelectOption<TeamMembershipLevel>)
            )}
            value={member.explicit_team_level}
        />
    )
}

function ActionsComponent(member: FusedTeamMemberType): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { removeMember } = useActions(teamMembersLogic)

    if (!user) {
        return null
    }

    function handleClick(): void {
        LemonDialog.open({
            title: `${
                member.user.uuid == user?.uuid
                    ? 'Leave'
                    : `Remove ${member.user.first_name} (${member.user.email}) from`
            } project ${currentTeam?.name}?`,
            secondaryButton: {
                children: 'Cancel',
            },
            primaryButton: {
                status: 'danger',
                children: member.user.uuid == user?.uuid ? 'Leave' : 'Remove',
                onClick: () => removeMember({ member }),
            },
        })
    }

    const allowDeletion =
        // You can leave, but only project admins can remove others
        ((currentTeam?.effective_membership_level &&
            currentTeam.effective_membership_level >= OrganizationMembershipLevel.Admin) ||
            member.user.uuid === user.uuid) &&
        // Only members without implicit access can leave or be removed
        member.organization_level < MINIMUM_IMPLICIT_ACCESS_LEVEL

    const isSelf = member.user.uuid === user.uuid

    return allowDeletion ? (
        <LemonButton
            status="danger"
            onClick={handleClick}
            data-attr="delete-team-membership"
            tooltip={isSelf ? 'Leave project' : 'Remove from project'}
        >
            {isSelf ? <IconLeave /> : <IconCancel />}
        </LemonButton>
    ) : null
}

export function ProjectTeamMembers(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { allMembers, allMembersLoading } = useValues(teamMembersLogic)
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Project,
    })

    if (!user) {
        return null
    }

    const columns: LemonTableColumns<FusedTeamMemberType> = [
        {
            key: 'user_profile_picture',
            render: function ProfilePictureRender(_, member) {
                return <ProfilePicture user={member.user} />
            },
            width: 32,
        },
        {
            title: 'Name',
            key: 'user_first_name',
            render: (_, member) =>
                member.user.uuid == user.uuid ? `${member.user.first_name} (you)` : member.user.first_name,
            sorter: (a, b) => a.user.first_name.localeCompare(b.user.first_name),
        },
        {
            title: 'Email',
            key: 'user_email',
            render: (_, member) => member.user.email,
            sorter: (a, b) => a.user.email.localeCompare(b.user.email),
        },
        {
            title: 'Level',
            key: 'level',
            render: function LevelRender(_, member) {
                return LevelComponent(member)
            },
            sorter: (a, b) => a.level - b.level,
        },
        {
            title: 'Joined At',
            dataIndex: 'joined_at',
            key: 'joined_at',
            render: (_, member) => humanFriendlyDetailedTime(member.joined_at),
            sorter: (a, b) => a.joined_at.localeCompare(b.joined_at),
        },
        {
            key: 'actions',
            align: 'center',
            render: function ActionsRender(_, member) {
                return ActionsComponent(member)
            },
        },
    ]

    return (
        <>
            <h3 className="flex justify-between items-center mt-4">
                Members with Project Access
                <AddMembersModalWithButton disabledReason={restrictionReason} />
            </h3>

            <LemonTable
                columns={columns}
                dataSource={allMembers}
                loading={allMembersLoading}
                data-attr="team-members-table"
            />
        </>
    )
}

export function ProjectAccessControl(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const newAccessControl = useFeatureFlag('ACCESS_CONTROL')

    if (newAccessControl) {
        return <AccessControlObject resource="project" resource_id={`${currentTeam?.id}`} />
    }

    return (
        <>
            <p>
                {currentTeam?.access_control ? (
                    <>
                        This project is{' '}
                        <b>
                            <IconLock style={{ color: 'var(--warning)', marginRight: 5 }} />
                            private
                        </b>
                        . Only members listed below are allowed to access it.
                    </>
                ) : (
                    <>
                        This project is{' '}
                        <b>
                            <IconUnlock style={{ marginRight: 5 }} />
                            open
                        </b>
                        . Any member of the organization can access it. To enable granular access control, make it
                        private.
                    </>
                )}
            </p>
            <LemonSwitch
                onChange={(checked) => {
                    // Let them uncheck it if it's already checked, but don't let them check it if they don't have the feature
                    checked
                        ? guardAvailableFeature(AvailableFeature.PROJECT_BASED_PERMISSIONING, () =>
                              updateCurrentTeam({ access_control: checked })
                          )
                        : updateCurrentTeam({ access_control: checked })
                }}
                checked={!!currentTeam?.access_control}
                disabledReason={
                    !currentOrganization
                        ? 'Organization not loaded'
                        : !currentTeam
                        ? 'Project not loaded'
                        : currentOrganizationLoading
                        ? 'Loading organization…'
                        : currentTeamLoading
                        ? 'Loading project…'
                        : restrictionReason
                }
                bordered
                label="Make project private"
            />

            {currentTeam?.access_control && <ProjectTeamMembers />}
        </>
    )
}
