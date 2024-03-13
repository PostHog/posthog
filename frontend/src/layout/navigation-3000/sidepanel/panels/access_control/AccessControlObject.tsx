import { IconCrown, IconLeave } from '@posthog/icons'
import {
    LemonButton,
    LemonSelect,
    LemonSelectMultiple,
    LemonSelectOption,
    LemonSnack,
    LemonTable,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { OrganizationMembershipLevel, TeamMembershipLevel } from 'lib/constants'
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
import { useState } from 'react'
import { MINIMUM_IMPLICIT_ACCESS_LEVEL, teamMembersLogic } from 'scenes/settings/project/teamMembersLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { FusedTeamMemberType } from '~/types'

import { accessControlLogic, AccessControlLogicProps, RoleWithAccess } from './accessControlLogic'

export function AccessControlObject({ resource }: AccessControlLogicProps): JSX.Element | null {
    return (
        <BindLogic logic={accessControlLogic} props={{ resource }}>
            <div className="space-y-4">
                <h3>Default access to this {resource}</h3>
                <AccessControlObjectDefaults />

                <h3>Members with explicit access to this {resource}</h3>
                <AccessControlObjectUsers />

                <h3>Roles with explicit access to this {resource}</h3>
                <AccessControlObjectRoles />
            </div>
        </BindLogic>
    )
}

function AccessControlObjectDefaults(): JSX.Element | null {
    const [level, setLevel] = useState<any>(null)

    return (
        <LemonSelect
            value={level}
            onChange={(newValue) => {
                setLevel(newValue)
            }}
            options={[
                {
                    value: null,
                    label: 'No access by default',
                },
                {
                    value: TeamMembershipLevel.Member,
                    label: 'Everyone is a member by default',
                },
                {
                    value: TeamMembershipLevel.Admin,
                    label: 'Everyone is an admin by default',
                },
            ]}
            fullWidth
        />
    )
}

function AccessControlObjectUsers(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { allMembers, allMembersLoading } = useValues(teamMembersLogic)

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
                member.user.uuid == user.uuid ? `${member.user.first_name} (me)` : member.user.first_name,
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
        <div className="space-y-2">
            <div className="flex gap-2">
                <div className="flex-1">
                    <LemonSelectMultiple
                        placeholder="Search for team members to add…"
                        value={[]}
                        // onChange={(newValues: string[]) => setExplicitCollaboratorsToBeAdded(newValues)}
                        filterOption={true}
                        mode="multiple"
                        data-attr="subscribed-emails"
                        options={[]}
                    />
                </div>
                <LemonButton type="primary" onClick={() => alert('todo')}>
                    Add
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={allMembers}
                loading={allMembersLoading}
                data-attr="team-members-table"
            />
        </div>
    )
}

function AccessControlObjectRoles(): JSX.Element | null {
    const { rolesWithAccess, rolesLoading } = useValues(accessControlLogic)

    const columns: LemonTableColumns<RoleWithAccess> = [
        {
            title: 'Role',
            key: 'role',
            render: (_, { role }) => role.name,
            sorter: (a, b) => a.role.name.localeCompare(b.role.name),
        },
        {
            title: 'Level',
            key: 'level',
            render: (_, { level }) => {
                return level
            },
        },
    ]

    return (
        <div className="space-y-2">
            <div className="flex gap-2">
                <div className="flex-1">
                    <LemonSelectMultiple
                        placeholder="Search for team members to add…"
                        value={[]}
                        // onChange={(newValues: string[]) => setExplicitCollaboratorsToBeAdded(newValues)}
                        filterOption={true}
                        mode="multiple"
                        data-attr="subscribed-emails"
                        options={[]}
                    />
                </div>
                <LemonButton type="primary" onClick={() => alert('todo')}>
                    Add
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={rolesWithAccess}
                loading={rolesLoading}
                data-attr="team-members-table"
            />
        </div>
    )
}

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
