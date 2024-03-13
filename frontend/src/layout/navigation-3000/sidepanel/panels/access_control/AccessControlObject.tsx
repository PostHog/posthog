import { IconCrown } from '@posthog/icons'
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
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter } from 'lib/utils'
import {
    getReasonForAccessLevelChangeProhibition,
    membershipLevelToName,
    teamMembershipLevelIntegers,
} from 'lib/utils/permissioning'
import { useState } from 'react'
import { teamMembersLogic } from 'scenes/settings/project/teamMembersLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AccessControlType, FusedTeamMemberType } from '~/types'

import { accessControlLogic, AccessControlLogicProps } from './accessControlLogic'

export function AccessControlObject(props: AccessControlLogicProps): JSX.Element | null {
    const { resource } = props

    const suffix = props.resource_id ? `this ${resource}` : `all ${resource}s`

    return (
        <BindLogic logic={accessControlLogic} props={props}>
            <div className="space-y-4">
                <h3>Default access to {suffix}</h3>
                <AccessControlObjectDefaults />

                <h3>Members with explicit access to {suffix}</h3>
                <AccessControlObjectUsers />

                <h3>Roles with explicit access to {suffix}</h3>
                <AccessControlObjectRoles />
            </div>
        </BindLogic>
    )
}

function AccessControlObjectDefaults(): JSX.Element | null {
    const { accessControlGlobal, accessControlsLoading } = useValues(accessControlLogic)
    const { updateAccessControlGlobal } = useActions(accessControlLogic)

    return (
        <LemonSelect
            value={accessControlGlobal?.access_level ?? null}
            onChange={(newValue) => {
                updateAccessControlGlobal(newValue)
            }}
            disabledReason={accessControlsLoading ? 'Loading…' : undefined}
            options={[
                {
                    value: null,
                    label: 'No access by default',
                },
                {
                    value: 'member',
                    label: 'Everyone is a member by default',
                },
                {
                    value: 'admin',
                    label: 'Everyone is an admin by default',
                },
            ]}
            fullWidth
        />
    )
}

function AccessControlObjectUsers(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { addableMembers, accessControlMembers, accessControlsLoading } = useValues(accessControlLogic)
    const { updateAccessControlMembers } = useActions(accessControlLogic)

    if (!user) {
        return null
    }

    // TODO: WHAT A MESS - Fix this to do the index mapping beforehand...
    const columns: LemonTableColumns<AccessControlType> = [
        {
            key: 'user_profile_picture',
            render: function ProfilePictureRender(_, { organization_membership }) {
                return <ProfilePicture user={organization_membership!.user} />
            },
            width: 32,
        },
        {
            title: 'Name',
            key: 'user_first_name',
            render: (_, { organization_membership }) => (
                <b>
                    {organization_membership!.user.uuid == user.uuid
                        ? `${organization_membership!.user.first_name} (you)`
                        : organization_membership!.user.first_name}
                </b>
            ),
            sorter: (a, b) =>
                a.organization_membership!.user.first_name.localeCompare(b.organization_membership!.user.first_name),
        },
        {
            title: 'Email',
            key: 'user_email',
            render: (_, { organization_membership }) => organization_membership!.user.email,
            sorter: (a, b) =>
                a.organization_membership!.user.email.localeCompare(b.organization_membership!.user.email),
        },
        {
            title: 'Level',
            key: 'level',
            render: function LevelRender(_, { access_level }) {
                return access_level
            },
        },
        // {
        //     title: 'Joined At',
        //     dataIndex: 'joined_at',
        //     key: 'joined_at',
        //     render: (_, member) => humanFriendlyDetailedTime(member.joined_at),
        //     sorter: (a, b) => a.joined_at.localeCompare(b.joined_at),
        // },
        // {
        //     key: 'actions',
        //     align: 'center',
        //     render: function ActionsRender(_, member) {
        //         return ActionsComponent(member)
        //     },
        // },
    ]

    return (
        <div className="space-y-2">
            <AddItemsControls
                placeholder="Search for team members to add…"
                onAdd={(newValues, level) => updateAccessControlMembers(newValues.map((member) => ({ member, level })))}
                options={addableMembers.map((member) => ({
                    key: member.id,
                    label: member.user.first_name,
                }))}
                levels={['member', 'admin']}
            />

            <LemonTable columns={columns} dataSource={accessControlMembers} loading={accessControlsLoading} />
        </div>
    )
}

function AccessControlObjectRoles(): JSX.Element | null {
    const { accessControlRoles, accessControlsLoading, addableRoles } = useValues(accessControlLogic)
    const { updateAccessControlRoles } = useActions(accessControlLogic)

    const columns: LemonTableColumns<AccessControlType> = [
        {
            title: 'Role',
            key: 'role',
            render: (_, { role }) => <b>{role!.name}</b>,
        },
        {
            title: 'Level',
            key: 'level',
            render: (_, { access_level }) => {
                return access_level
            },
        },
    ]

    return (
        <div className="space-y-2">
            <AddItemsControls
                placeholder="Search for roles to add…"
                onAdd={(newValues, level) => updateAccessControlRoles(newValues.map((role) => ({ role, level })))}
                options={addableRoles.map((role) => ({
                    key: role.id,
                    label: role.name,
                }))}
                levels={['member', 'admin']}
            />

            <LemonTable columns={columns} dataSource={accessControlRoles} loading={accessControlsLoading} />
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

function AddItemsControls(props: {
    placeholder: string
    onAdd: (newValues: string[], level: AccessControlType['access_level']) => void
    options: {
        key: string
        label: string
    }[]
    levels: AccessControlType['access_level'][]
}): JSX.Element | null {
    const [items, setItems] = useState<string[]>([])
    const [level, setLevel] = useState<AccessControlType['access_level']>()

    const onSubmit = items.length && level ? (): void => props.onAdd(items, level) : undefined

    return (
        <div className="flex gap-2">
            <div className="flex-1">
                <LemonSelectMultiple
                    placeholder={props.placeholder}
                    value={items}
                    onChange={(newValues: string[]) => setItems(newValues)}
                    filterOption={true}
                    mode="multiple"
                    options={props.options}
                />
            </div>
            <LemonSelect
                placeholder="Select level..."
                options={props.levels.map((level) => ({
                    value: level,
                    label: capitalizeFirstLetter(level ?? ''),
                }))}
                value={level}
                onChange={(newValue) => setLevel(newValue)}
            />
            <LemonButton
                type="primary"
                onClick={onSubmit}
                disabledReason={!onSubmit ? 'Please choose what you want to add and at what level' : undefined}
            >
                Add
            </LemonButton>
        </div>
    )
}
