import { BindLogic, useActions, useAsyncActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonSelectProps,
    LemonTable,
    Tooltip,
} from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { UserSelectItem } from 'lib/components/UserSelectItem'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { ProfileBubbles, ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { capitalizeFirstLetter, fullName } from 'lib/utils'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    AccessControlLevel,
    AccessControlTypeMember,
    AccessControlTypeOrganizationAdmins,
    AccessControlTypeRole,
    AvailableFeature,
    OrganizationMemberType,
    RoleMemberType,
    RoleType,
} from '~/types'

import { AccessControlLogicProps, accessControlLogic } from './accessControlLogic'

export function AccessControlObject(props: AccessControlLogicProps): JSX.Element | null {
    const { canEditAccessControls, humanReadableResource } = useValues(accessControlLogic(props))

    const suffix = `this ${humanReadableResource}`

    return (
        <BindLogic logic={accessControlLogic} props={props}>
            <div>
                <h2>{props.title}</h2>
                <p>{props.description}</p>
                <PayGateMini feature={AvailableFeature.ADVANCED_PERMISSIONS}>
                    <div className="deprecated-space-y-6">
                        {canEditAccessControls === false ? (
                            <LemonBanner type="warning">
                                <Tooltip
                                    title={`You don't have permission to edit access controls for ${suffix}. You must be the creator of it, a Project admin, an Organization admin, or have manager access to the resource.`}
                                >
                                    <span className="font-medium">Permission required</span>
                                </Tooltip>
                            </LemonBanner>
                        ) : null}

                        <div className="deprecated-space-y-2">
                            <h3>Default access to {suffix}</h3>
                            <AccessControlObjectDefaults />
                        </div>

                        <AccessControlObjectUsers />

                        {/* Put this inside of Advanced Permissions (access control) so two aren't shown at once */}
                        <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS}>
                            <AccessControlObjectRoles />
                        </PayGateMini>
                    </div>
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
                guardAvailableFeature(AvailableFeature.ADVANCED_PERMISSIONS, () => {
                    updateAccessControlDefault(newValue as AccessControlLevel)
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
    const {
        resource,
        membersById,
        addableMembers,
        accessControlMembers,
        accessControlsLoading,
        availableLevels,
        canEditAccessControls,
    } = useValues(accessControlLogic)
    const { updateAccessControlMembers } = useAsyncActions(accessControlLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    const [modelOpen, setModelOpen] = useState(false)

    if (!user) {
        return null
    }

    const member = (ac: AccessControlTypeMember): OrganizationMemberType => {
        return membersById[ac.organization_member]
    }

    // TODO(@zach): show project admins (that are not organization admins) in the table
    const columns: LemonTableColumns<AccessControlTypeMember | AccessControlTypeOrganizationAdmins> = [
        {
            key: 'user',
            title: 'User',
            render: (_, ac) =>
                ac.resource === 'organization' ? (
                    <div className="flex gap-1 py-1">
                        <ProfileBubbles
                            limit={3}
                            people={(ac as AccessControlTypeOrganizationAdmins)?.organization_admin_members?.map(
                                (member) => ({
                                    email: membersById[member]?.user.email,
                                    name: fullName(membersById[member]?.user),
                                })
                            )}
                        />
                        <p className="text-secondary mb-0">
                            {(ac as AccessControlTypeOrganizationAdmins)?.organization_admin_members.length > 1
                                ? 'have access as organization admins'
                                : 'has access as an organization admin'}
                        </p>
                    </div>
                ) : (
                    <div className="ph-no-capture flex items-center gap-2">
                        <ProfilePicture user={member(ac as AccessControlTypeMember)?.user} />
                        <div>
                            <p className="font-medium mb-0">
                                {member(ac as AccessControlTypeMember)?.user.uuid == user.uuid
                                    ? `${fullName(member(ac as AccessControlTypeMember)?.user)} (you)`
                                    : fullName(member(ac as AccessControlTypeMember)?.user)}
                            </p>
                            <p className="text-secondary mb-0">{member(ac as AccessControlTypeMember)?.user.email}</p>
                        </div>
                    </div>
                ),
            sorter: (a, b) =>
                fullName(member(a as AccessControlTypeMember)?.user).localeCompare(
                    fullName(member(b as AccessControlTypeMember)?.user)
                ),
        },
        {
            key: 'level',
            title: 'Level',
            width: 0,
            render: function LevelRender(_, ac) {
                return ac.resource === 'organization' ? (
                    <div className="my-1">
                        {/* Shown as disabled for visibility */}
                        <SimplLevelComponent
                            size="small"
                            level={resource === 'project' ? AccessControlLevel.Admin : AccessControlLevel.Editor}
                            disabled={true}
                            levels={availableLevels}
                            onChange={() => {}}
                        />
                    </div>
                ) : (
                    <div className="my-1">
                        <SimplLevelComponent
                            size="small"
                            level={ac.access_level}
                            levels={availableLevels}
                            onChange={(level) =>
                                void updateAccessControlMembers([{ member: ac.organization_member as string, level }])
                            }
                        />
                    </div>
                )
            },
        },
        {
            key: 'remove',
            width: 0,
            render: (_, ac) => {
                return ac.resource === 'organization' ? null : (
                    <RemoveAccessButton
                        subject="member"
                        onConfirm={() =>
                            void updateAccessControlMembers([{ member: ac.organization_member as string, level: null }])
                        }
                    />
                )
            },
        },
    ]

    return (
        <>
            <div className="deprecated-space-y-2">
                <div className="flex gap-2 items-center justify-between">
                    <h3 className="mb-0">Members</h3>
                    <LemonButton
                        type="primary"
                        onClick={() => setModelOpen(true)}
                        disabledReason={!canEditAccessControls ? 'You cannot edit this' : undefined}
                    >
                        Add
                    </LemonButton>
                </div>

                <LemonTable columns={columns} dataSource={accessControlMembers} loading={accessControlsLoading} />
            </div>

            <AddItemsControlsModal
                modelOpen={modelOpen}
                setModelOpen={setModelOpen}
                placeholder="Search for team members to add…"
                onAdd={async (newValues, level) => {
                    if (guardAvailableFeature(AvailableFeature.ADVANCED_PERMISSIONS)) {
                        await updateAccessControlMembers(newValues.map((member) => ({ member, level })))
                        setModelOpen(false)
                    }
                }}
                options={addableMembers.map((member: OrganizationMemberType) => ({
                    key: member.id,
                    label: `${fullName(member.user)} ${member.user.email}`,
                    labelComponent: <UserSelectItem user={member.user} />,
                }))}
            />
        </>
    )
}

function AccessControlObjectRoles(): JSX.Element | null {
    const {
        accessControlRoles,
        accessControlsLoading,
        addableRoles,
        rolesById,
        availableLevels,
        canEditAccessControls,
    } = useValues(accessControlLogic)
    const { updateAccessControlRoles } = useAsyncActions(accessControlLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    const [modelOpen, setModelOpen] = useState(false)

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
                            rolesById[role]?.members?.map((member: RoleMemberType) => ({
                                email: member.user.email,
                                name: fullName(member.user),
                                title: `${fullName(member.user)} <${member.user.email}>`,
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
        <>
            <div className="deprecated-space-y-2">
                <div className="flex gap-2 items-center justify-between">
                    <h3 className="mb-0">Roles</h3>
                    <LemonButton
                        type="primary"
                        onClick={() => setModelOpen(true)}
                        disabledReason={!canEditAccessControls ? 'You cannot edit this' : undefined}
                    >
                        Add
                    </LemonButton>
                </div>

                <LemonTable columns={columns} dataSource={accessControlRoles} loading={accessControlsLoading} />
            </div>

            <AddItemsControlsModal
                modelOpen={modelOpen}
                setModelOpen={setModelOpen}
                placeholder="Search for roles to add…"
                onAdd={async (newValues, level) => {
                    if (guardAvailableFeature(AvailableFeature.ADVANCED_PERMISSIONS)) {
                        await updateAccessControlRoles(newValues.map((role) => ({ role, level })))
                        setModelOpen(false)
                    }
                }}
                options={addableRoles.map((role: RoleType) => ({
                    key: role.id,
                    label: role.name,
                }))}
            />
        </>
    )
}

function SimplLevelComponent(props: {
    size?: LemonSelectProps<any>['size']
    level: AccessControlLevel | null
    levels: AccessControlLevel[]
    onChange: (newValue: AccessControlLevel) => void
    disabled?: boolean
}): JSX.Element | null {
    const { canEditAccessControls, minimumAccessLevel } = useValues(accessControlLogic)

    return (
        <LemonSelect
            size={props.size}
            placeholder="Select level..."
            value={props.level}
            onChange={(newValue) => props.onChange(newValue as AccessControlLevel)}
            disabledReason={!canEditAccessControls || props.disabled ? 'You cannot edit this' : undefined}
            options={props.levels.map((level) => {
                const isDisabled = minimumAccessLevel
                    ? props.levels.indexOf(level) < props.levels.indexOf(minimumAccessLevel)
                    : false
                return {
                    value: level,
                    label: capitalizeFirstLetter(level ?? ''),
                    disabledReason: isDisabled ? 'Not available for this resource type' : undefined,
                }
            })}
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
            icon={<IconTrash />}
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

function AddItemsControlsModal(props: {
    modelOpen: boolean
    setModelOpen: (open: boolean) => void
    placeholder: string
    onAdd: (newValues: string[], level: AccessControlLevel) => Promise<void>
    options: {
        key: string
        label: string
    }[]
}): JSX.Element | null {
    const { availableLevels, canEditAccessControls } = useValues(accessControlLogic)
    // TODO: Move this into a form logic
    const [items, setItems] = useState<string[]>([])
    const [level, setLevel] = useState<AccessControlLevel>(availableLevels[0] ?? null)

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
        <LemonModal
            isOpen={props.modelOpen || false}
            onClose={() => props.setModelOpen(false)}
            title="Add access"
            maxWidth="30rem"
            description="Allow other users or roles to access this resource"
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton type="secondary" onClick={() => props.setModelOpen(false)}>
                        Cancel
                    </LemonButton>
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
            }
        >
            <div className="flex gap-2 items-center w-full">
                <div className="min-w-[16rem] w-full">
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
            </div>
        </LemonModal>
    )
}
