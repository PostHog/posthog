import { IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonSelect,
    LemonSelectMultiple,
    LemonSelectProps,
    LemonTable,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useAsyncActions, useValues } from 'kea'
import { UserSelectItem, usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { ProfileBubbles, ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { capitalizeFirstLetter } from 'lib/utils'
import { useState } from 'react'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AccessControlType, AccessControlTypeMember, AccessControlTypeRole, OrganizationMemberType } from '~/types'

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
    const { accessControlProject, accessControlsLoading, availableLevels } = useValues(accessControlLogic)
    const { updateAccessControlProject } = useActions(accessControlLogic)

    return (
        <LemonSelect
            value={accessControlProject?.access_level ?? null}
            onChange={(newValue) => {
                updateAccessControlProject(newValue)
            }}
            disabledReason={accessControlsLoading ? 'Loading…' : undefined}
            dropdownMatchSelectWidth={false}
            options={[
                {
                    value: null,
                    label: 'No access by default',
                },
                ...availableLevels.map((level) => ({
                    value: level,
                    // TODO: Correct "a" and "an"
                    label: `Everyone is a ${level} by default`,
                })),
            ]}
        />
    )
}

function AccessControlObjectUsers(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { membersById, addableMembers, accessControlMembers, accessControlsLoading, availableLevels } =
        useValues(accessControlLogic)
    const { updateAccessControlMembers } = useAsyncActions(accessControlLogic)

    if (!user) {
        return null
    }

    const member = (ac: AccessControlTypeMember): OrganizationMemberType => {
        return membersById[ac.organization_member]
    }

    // TODO: WHAT A MESS - Fix this to do the index mapping beforehand...
    const columns: LemonTableColumns<AccessControlTypeMember> = [
        {
            key: 'user_profile_picture',
            render: function ProfilePictureRender(_, ac) {
                return <ProfilePicture user={member(ac)?.user} />
            },
            width: 32,
        },
        {
            title: 'Name',
            key: 'user_first_name',
            render: (_, ac) => (
                <b>
                    {member(ac)?.user.uuid == user.uuid
                        ? `${member(ac)?.user.first_name} (you)`
                        : member(ac)?.user.first_name}
                </b>
            ),
            sorter: (a, b) => member(a)?.user.first_name.localeCompare(member(b)?.user.first_name),
        },
        {
            title: 'Email',
            key: 'user_email',
            render: (_, ac) => member(ac)?.user.email,
            sorter: (a, b) => member(a)?.user.email.localeCompare(member(b)?.user.email),
        },
        {
            title: 'Level',
            key: 'level',
            width: 0,
            render: function LevelRender(_, { access_level, organization_member }) {
                return (
                    <div className="my-1">
                        <SimplLevelComponent
                            size="small"
                            level={access_level}
                            onChange={(level) =>
                                void updateAccessControlMembers([{ member: organization_member, level }])
                            }
                        />
                    </div>
                )
            },
        },
        {
            key: 'remove',
            width: 0,
            render: (_, { organization_member }) => {
                return (
                    <RemoveAccessButton
                        subject="member"
                        onConfirm={() =>
                            void updateAccessControlMembers([{ member: organization_member, level: null }])
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="space-y-2">
            <AddItemsControls
                placeholder="Search for team members to add…"
                onAdd={(newValues, level) => updateAccessControlMembers(newValues.map((member) => ({ member, level })))}
                options={addableMembers.map((member) => ({
                    key: member.id,
                    label: `${member.user.first_name} ${member.user.email}`,
                    labelComponent: <UserSelectItem user={member.user} />,
                }))}
                levels={availableLevels}
            />

            <LemonTable columns={columns} dataSource={accessControlMembers} loading={accessControlsLoading} />
        </div>
    )
}

function AccessControlObjectRoles(): JSX.Element | null {
    const { accessControlRoles, accessControlsLoading, addableRoles, rolesById } = useValues(accessControlLogic)
    const { updateAccessControlRoles } = useAsyncActions(accessControlLogic)

    const columns: LemonTableColumns<AccessControlTypeRole> = [
        {
            title: 'Role',
            key: 'role',
            width: 0,
            render: (_, { role }) => (
                <span className="whitespace-nowrap">
                    <LemonTableLink
                        to={urls.settings('organization-rbac') + `#role=${role}`}
                        title={rolesById[role]?.name}
                    />
                </span>
            ),
        },
        {
            title: 'Members',
            key: 'members',
            render: (_, { role }) => {
                return (
                    <ProfileBubbles
                        people={
                            rolesById[role]?.members?.map((member) => ({
                                email: member.user.email,
                                name: member.user.first_name,
                                title: `${member.user.first_name} <${member.user.email}>`,
                            })) ?? []
                        }
                    />
                )
            },
        },
        {
            title: 'Level',
            key: 'level',
            width: 0,
            render: (_, { access_level, role }) => {
                return (
                    <div className="my-1">
                        <SimplLevelComponent
                            size="small"
                            level={access_level}
                            onChange={(level) => void updateAccessControlRoles([{ role, level }])}
                        />
                    </div>
                )
            },
        },
        {
            key: 'remove',
            width: 0,
            render: (_, { role }) => {
                return (
                    <RemoveAccessButton
                        subject="role"
                        onConfirm={() => void updateAccessControlRoles([{ role, level: null }])}
                    />
                )
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

// function LevelComponent(member: FusedTeamMemberType): JSX.Element | null {
//     const { user } = useValues(userLogic)
//     const { currentTeam } = useValues(teamLogic)
//     const { changeUserAccessLevel } = useActions(teamMembersLogic)

//     const myMembershipLevel = isAuthenticatedTeam(currentTeam) ? currentTeam.effective_membership_level : null

//     if (!user) {
//         return null
//     }

//     const isImplicit = member.organization_level >= OrganizationMembershipLevel.Admin
//     const levelName = membershipLevelToName.get(member.level) ?? `unknown (${member.level})`

//     const allowedLevels = teamMembershipLevelIntegers.filter(
//         (listLevel) => !getReasonForAccessLevelChangeProhibition(myMembershipLevel, user, member, listLevel)
//     )

//     const possibleOptions = member.explicit_team_level
//         ? allowedLevels.concat([member.explicit_team_level])
//         : allowedLevels

//     const disallowedReason = isImplicit
//         ? `This user is a member of the project implicitly due to being an organization ${levelName}.`
//         : getReasonForAccessLevelChangeProhibition(myMembershipLevel, user, member, allowedLevels)

//     return disallowedReason ? (
//         <Tooltip title={disallowedReason}>
//             <LemonSnack className="capitalize">
//                 {member.level === OrganizationMembershipLevel.Owner && <IconCrown className="mr-2" />}
//                 {levelName}
//             </LemonSnack>
//         </Tooltip>
//     ) : (
//         <LemonSelect
//             dropdownMatchSelectWidth={false}
//             onChange={(listLevel) => {
//                 if (listLevel !== null) {
//                     changeUserAccessLevel(member.user, listLevel)
//                 }
//             }}
//             options={possibleOptions.map(
//                 (listLevel) =>
//                     ({
//                         value: listLevel,
//                         disabled: listLevel === member.explicit_team_level,
//                         label:
//                             listLevel > member.level
//                                 ? membershipLevelToName.get(listLevel)
//                                 : membershipLevelToName.get(listLevel),
//                     } as LemonSelectOption<TeamMembershipLevel>)
//             )}
//             value={member.explicit_team_level}
//         />
//     )
// }

function SimplLevelComponent(props: {
    size?: LemonSelectProps<any>['size']
    level: AccessControlType['access_level'] | null
    onChange: (newValue: AccessControlType['access_level']) => void
}): JSX.Element | null {
    const { availableLevels } = useValues(accessControlLogic)

    return (
        <LemonSelect
            size={props.size}
            placeholder="Select level..."
            value={props.level}
            onChange={(newValue) => props.onChange(newValue)}
            options={availableLevels.map((level) => ({
                value: level,
                label: capitalizeFirstLetter(level ?? ''),
            }))}
        />
    )
}

function RemoveAccessButton({
    onConfirm,
    subject,
}: {
    onConfirm: () => void
    subject: 'member' | 'role'
}): JSX.Element {
    return (
        <LemonButton
            icon={<IconX />}
            status="danger"
            size="small"
            onClick={() =>
                LemonDialog.open({
                    title: 'Remove access',
                    content: `Are you sure you want to remove this ${subject}'s access?`,
                    primaryButton: {
                        children: 'Remove',
                        status: 'danger',
                        onClick: () => onConfirm(),
                    },
                })
            }
        />
    )
}

function AddItemsControls(props: {
    placeholder: string
    onAdd: (newValues: string[], level: AccessControlType['access_level']) => Promise<void>
    options: {
        key: string
        label: string
    }[]
    levels: AccessControlType['access_level'][]
}): JSX.Element | null {
    const [items, setItems] = useState<string[]>([])
    const [level, setLevel] = useState<AccessControlType['access_level']>(null)

    const onSubmit =
        items.length && level
            ? (): void =>
                  void props.onAdd(items, level).then(() => {
                      setItems([])
                      setLevel(null)
                  })
            : undefined

    return (
        <div className="flex gap-2">
            <div className="min-w-[16rem]">
                <LemonSelectMultiple
                    placeholder={props.placeholder}
                    value={items}
                    onChange={(newValues: string[]) => setItems(newValues)}
                    filterOption={true}
                    mode="multiple"
                    options={props.options}
                />
            </div>
            <SimplLevelComponent level={level} onChange={setLevel} />

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
