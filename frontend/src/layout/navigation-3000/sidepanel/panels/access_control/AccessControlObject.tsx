import { IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInputSelect,
    LemonSelect,
    LemonSelectProps,
    LemonTable,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useAsyncActions, useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { UserSelectItem } from 'lib/components/UserSelectItem'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { ProfileBubbles, ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { capitalizeFirstLetter } from 'lib/utils'
import { useEffect, useState } from 'react'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    AccessControlType,
    AccessControlTypeMember,
    AccessControlTypeRole,
    AvailableFeature,
    OrganizationMemberType,
} from '~/types'

import { accessControlLogic, AccessControlLogicProps } from './accessControlLogic'

export function AccessControlObject(props: AccessControlLogicProps): JSX.Element | null {
    const { canEditAccessControls, humanReadableResource } = useValues(accessControlLogic(props))

    const suffix = `this ${humanReadableResource}`

    return (
        <BindLogic logic={accessControlLogic} props={props}>
            <div className="space-y-4">
                {canEditAccessControls === false ? (
                    <LemonBanner type="info">
                        <b>You don't have permission to edit access controls for {suffix}.</b>
                        <br />
                        You must be the creator of it, a Project Admin, or an Organization Admin.
                    </LemonBanner>
                ) : null}
                <h3>Default access to {suffix}</h3>
                <AccessControlObjectDefaults />

                <h3>Members</h3>
                <PayGateMini feature={AvailableFeature.PROJECT_BASED_PERMISSIONING}>
                    <AccessControlObjectUsers />
                </PayGateMini>

                <h3>Roles</h3>
                <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS}>
                    <AccessControlObjectRoles />
                </PayGateMini>
            </div>
        </BindLogic>
    )
}

function AccessControlObjectDefaults(): JSX.Element | null {
    const { accessControlDefault, accessControlDefaultOptions, accessControlsLoading, canEditAccessControls } =
        useValues(accessControlLogic)
    const { updateAccessControlDefault } = useActions(accessControlLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    return (
        <LemonSelect
            placeholder="Loading..."
            value={accessControlDefault?.access_level ?? undefined}
            onChange={(newValue) => {
                guardAvailableFeature(AvailableFeature.PROJECT_BASED_PERMISSIONING, () => {
                    updateAccessControlDefault(newValue)
                })
            }}
            disabledReason={
                accessControlsLoading ? 'Loading…' : !canEditAccessControls ? 'You cannot edit this' : undefined
            }
            dropdownMatchSelectWidth={false}
            options={accessControlDefaultOptions}
        />
    )
}

function AccessControlObjectUsers(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { membersById, addableMembers, accessControlMembers, accessControlsLoading, availableLevels } =
        useValues(accessControlLogic)
    const { updateAccessControlMembers } = useAsyncActions(accessControlLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

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
                            levels={availableLevels}
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
                onAdd={async (newValues, level) => {
                    if (guardAvailableFeature(AvailableFeature.PROJECT_BASED_PERMISSIONING)) {
                        await updateAccessControlMembers(newValues.map((member) => ({ member, level })))
                    }
                }}
                options={addableMembers.map((member) => ({
                    key: member.id,
                    label: `${member.user.first_name} ${member.user.email}`,
                    labelComponent: <UserSelectItem user={member.user} />,
                }))}
            />

            <LemonTable columns={columns} dataSource={accessControlMembers} loading={accessControlsLoading} />
        </div>
    )
}

function AccessControlObjectRoles(): JSX.Element | null {
    const { accessControlRoles, accessControlsLoading, addableRoles, rolesById, availableLevels } =
        useValues(accessControlLogic)
    const { updateAccessControlRoles } = useAsyncActions(accessControlLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    const columns: LemonTableColumns<AccessControlTypeRole> = [
        {
            title: 'Role',
            key: 'role',
            width: 0,
            render: (_, { role }) => (
                <span className="whitespace-nowrap">
                    <LemonTableLink
                        to={urls.settings('organization-roles') + `#role=${role}`}
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
                            levels={availableLevels}
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
                onAdd={async (newValues, level) => {
                    if (guardAvailableFeature(AvailableFeature.PROJECT_BASED_PERMISSIONING)) {
                        await updateAccessControlRoles(newValues.map((role) => ({ role, level })))
                    }
                }}
                options={addableRoles.map((role) => ({
                    key: role.id,
                    label: role.name,
                }))}
            />

            <LemonTable columns={columns} dataSource={accessControlRoles} loading={accessControlsLoading} />
        </div>
    )
}

function SimplLevelComponent(props: {
    size?: LemonSelectProps<any>['size']
    level: AccessControlType['access_level'] | null
    levels: AccessControlType['access_level'][]
    onChange: (newValue: AccessControlType['access_level']) => void
}): JSX.Element | null {
    const { canEditAccessControls } = useValues(accessControlLogic)

    return (
        <LemonSelect
            size={props.size}
            placeholder="Select level..."
            value={props.level}
            onChange={(newValue) => props.onChange(newValue)}
            disabledReason={!canEditAccessControls ? 'You cannot edit this' : undefined}
            options={props.levels.map((level) => ({
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
    const { canEditAccessControls } = useValues(accessControlLogic)

    return (
        <LemonButton
            icon={<IconX />}
            status="danger"
            size="small"
            disabledReason={!canEditAccessControls ? 'You cannot edit this' : undefined}
            onClick={() =>
                LemonDialog.open({
                    title: 'Remove access',
                    content: `Are you sure you want to remove this ${subject}'s explicit access?`,
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
}): JSX.Element | null {
    const { availableLevels, canEditAccessControls } = useValues(accessControlLogic)
    // TODO: Move this into a form logic
    const [items, setItems] = useState<string[]>([])
    const [level, setLevel] = useState<AccessControlType['access_level']>(availableLevels[0] ?? null)

    useEffect(() => {
        setLevel(availableLevels[0] ?? null)
    }, [availableLevels])

    const onSubmit =
        items.length && level
            ? (): void =>
                  void props.onAdd(items, level).then(() => {
                      setItems([])
                      setLevel(availableLevels[0] ?? null)
                  })
            : undefined

    return (
        <div className="flex gap-2 items-center">
            <div className="min-w-[16rem]">
                <LemonInputSelect
                    placeholder={props.placeholder}
                    value={items}
                    onChange={(newValues: string[]) => setItems(newValues)}
                    mode="multiple"
                    options={props.options}
                    disabled={!canEditAccessControls}
                />
            </div>
            <SimplLevelComponent levels={availableLevels} level={level} onChange={setLevel} />

            <LemonButton
                type="primary"
                onClick={onSubmit}
                disabledReason={
                    !canEditAccessControls
                        ? 'You cannot edit this'
                        : !onSubmit
                        ? 'Please choose what you want to add and at what level'
                        : undefined
                }
            >
                Add
            </LemonButton>
        </div>
    )
}
