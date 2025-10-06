import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'kea-forms'
import { useMemo, useState } from 'react'

import {
    LemonButton,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
    ProfileBubbles,
    ProfilePicture,
} from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { UserSelectItem } from 'lib/components/UserSelectItem'
import { fullName } from 'lib/utils'

import { APIScopeObject, AccessControlLevel, AvailableFeature } from '~/types'

import {
    DefaultResourceAccessControls,
    MemberResourceAccessControls,
    RoleResourceAccessControls,
    resourcesAccessControlLogic,
} from './resourcesAccessControlLogic'

const pluralizeResource = (resource: APIScopeObject): string => {
    if (resource === 'revenue_analytics') {
        return 'revenue analytics'
    }

    return resource.replace(/_/g, ' ') + 's'
}

const SummarizeAccessLevels = ({
    accessControlByResource,
}: {
    accessControlByResource: Record<APIScopeObject, any>
}): JSX.Element => {
    const entries = Object.entries(accessControlByResource)
        .map(([resource, ac]) => ({
            resource,
            level: ac?.access_level,
        }))
        .filter((entry) => entry.level !== null && entry.level !== undefined)

    if (entries.length === 0) {
        return <span>No default permissions</span>
    }

    return (
        <div className="flex gap-2 flex-wrap">
            {entries.map(({ resource, level }) => (
                <LemonTag key={resource} type="default">
                    {capitalizeFirstLetter(pluralizeResource(resource as APIScopeObject))}:{' '}
                    {capitalizeFirstLetter(level)}
                </LemonTag>
            ))}
        </div>
    )
}

export function ResourcesAccessControls(): JSX.Element {
    const {
        defaultResourceAccessControls,
        memberResourceAccessControls,
        roleResourceAccessControls,
        canEditRoleBasedAccessControls,
        addableMembers,
        addableRoles,
        resourceAccessControlsLoading,
        memberModalOpen,
        editingMember,
        roleModalOpen,
        editingRole,
        defaultModalOpen,
    } = useValues(resourcesAccessControlLogic)
    const {
        updateResourceAccessControls,
        openMemberModal,
        closeMemberModal,
        openRoleModal,
        closeRoleModal,
        openDefaultModal,
        closeDefaultModal,
    } = useActions(resourcesAccessControlLogic)

    // Default table
    const defaultColumns: LemonTableColumns<DefaultResourceAccessControls> = [
        {
            title: '',
            key: 'default',
            width: 300,
            render: () => 'All roles and members',
        },
        {
            title: 'Defaults',
            key: 'defaults',
            render: (_, { accessControlByResource }) => {
                return <SummarizeAccessLevels accessControlByResource={accessControlByResource} />
            },
        },
        {
            title: '',
            key: 'actions',
            width: 100,
            align: 'right',
            render: () => {
                return (
                    <LemonButton
                        size="small"
                        onClick={openDefaultModal}
                        disabledReason={!canEditRoleBasedAccessControls ? 'You cannot edit this' : undefined}
                    >
                        Edit
                    </LemonButton>
                )
            },
        },
    ]

    // Members table
    const memberColumns: LemonTableColumns<MemberResourceAccessControls> = [
        {
            title: 'User',
            key: 'member',
            width: 300,
            render: (_, { organization_member }) => {
                return (
                    <div className="flex items-center gap-2">
                        <ProfilePicture user={organization_member!.user} />
                        <div>
                            <p className="font-medium mb-0">{fullName(organization_member!.user)}</p>
                            <p className="text-secondary mb-0">{organization_member!.user.email}</p>
                        </div>
                    </div>
                )
            },
        },
        {
            title: 'Permissions',
            key: 'permissions',
            render: (_, { accessControlByResource }) => {
                return <SummarizeAccessLevels accessControlByResource={accessControlByResource} />
            },
        },
        {
            title: '',
            key: 'actions',
            width: 100,
            align: 'right',
            render: (_, member) => {
                return (
                    <LemonButton
                        size="small"
                        onClick={() => openMemberModal(member)}
                        disabledReason={!canEditRoleBasedAccessControls ? 'You cannot edit this' : undefined}
                    >
                        Edit
                    </LemonButton>
                )
            },
        },
    ]

    // Roles table
    const roleColumns: LemonTableColumns<RoleResourceAccessControls> = [
        {
            title: 'Role',
            key: 'role',
            width: 300,
            render: (_, { role }) => {
                return <span>{role!.name}</span>
            },
        },
        {
            title: 'Members',
            key: 'members',
            render: (_, { role }) => {
                return (
                    <div className="flex space-x-2">
                        {role!.members.length ? (
                            <ProfileBubbles
                                people={
                                    role?.members?.map((member) => ({
                                        email: member.user.email,
                                        name: fullName(member.user),
                                        title: `${fullName(member.user)} <${member.user.email}>`,
                                    })) ?? []
                                }
                            />
                        ) : (
                            'No members'
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Permissions',
            key: 'permissions',
            render: (_, { accessControlByResource }) => {
                return <SummarizeAccessLevels accessControlByResource={accessControlByResource} />
            },
        },
        {
            title: '',
            key: 'actions',
            width: 100,
            align: 'right',
            render: (_, role) => {
                return (
                    <LemonButton
                        size="small"
                        onClick={() => openRoleModal(role)}
                        disabledReason={!canEditRoleBasedAccessControls ? 'You cannot edit this' : undefined}
                    >
                        Edit
                    </LemonButton>
                )
            },
        },
    ]

    return (
        <div className="space-y-4">
            <h2>Resource permissions</h2>
            <p>
                Use resource permissions to assign project-wide access to specific resources (e.g. insights, features
                flags, etc.) for individuals and roles.
            </p>

            <PayGateMini feature={AvailableFeature.ADVANCED_PERMISSIONS}>
                <div className="space-y-6">
                    {/* Default permissions table */}
                    <div className="space-y-2">
                        <h3>Project defaults</h3>
                        <LemonTable columns={defaultColumns} dataSource={[defaultResourceAccessControls]} />
                    </div>

                    {/* Members permissions table */}
                    <ResourcesAccessControlMembers
                        memberResourceAccessControls={memberResourceAccessControls}
                        memberColumns={memberColumns}
                        canEditRoleBasedAccessControls={canEditRoleBasedAccessControls}
                        openMemberModal={openMemberModal}
                    />

                    <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS}>
                        {/* Roles permissions table */}
                        <ResourcesAccessControlRoles
                            roleResourceAccessControls={roleResourceAccessControls}
                            roleColumns={roleColumns}
                            canEditRoleBasedAccessControls={canEditRoleBasedAccessControls}
                            openRoleModal={openRoleModal}
                        />
                    </PayGateMini>
                </div>
            </PayGateMini>

            {/* Modals for adding/editing access controls */}
            {memberModalOpen && (
                <ResourceAccessControlModal
                    key={editingMember?.organization_member?.id || 'new'}
                    modalOpen={memberModalOpen}
                    setModalOpen={closeMemberModal}
                    placeholder="Search for team members to add…"
                    onSave={handleSaveMemberAccess}
                    options={addableMembers.map((member) => ({
                        key: member.id,
                        label: `${fullName(member.user)} ${member.user.email}`,
                        labelComponent: <UserSelectItem user={member.user} />,
                    }))}
                    type="member"
                    editingEntry={editingMember}
                    loading={resourceAccessControlsLoading}
                />
            )}

            {roleModalOpen && (
                <ResourceAccessControlModal
                    key={editingRole?.role?.id || 'new'}
                    modalOpen={roleModalOpen}
                    setModalOpen={closeRoleModal}
                    placeholder="Search for roles to add…"
                    onSave={handleSaveRoleAccess}
                    options={addableRoles.map((role) => ({
                        key: role.id,
                        label: role.name,
                    }))}
                    type="role"
                    editingEntry={editingRole}
                    loading={resourceAccessControlsLoading}
                />
            )}

            {defaultModalOpen && (
                <DefaultResourceAccessControlModal
                    key="default"
                    modalOpen={defaultModalOpen}
                    setModalOpen={closeDefaultModal}
                    onSave={handleSaveDefaultAccess}
                    defaultResourceAccessControls={defaultResourceAccessControls}
                    loading={resourceAccessControlsLoading}
                />
            )}
        </div>
    )

    async function handleSaveDefaultAccess(
        resourceLevels: Partial<Record<APIScopeObject, AccessControlLevel | null>>
    ): Promise<void> {
        const accessControls = []

        for (const [resource, level] of Object.entries(resourceLevels)) {
            accessControls.push({
                resource: resource as APIScopeObject,
                organization_member: null,
                role: null,
                access_level: level,
            })
        }

        if (accessControls.length > 0) {
            updateResourceAccessControls(accessControls, 'default')
        }
    }

    async function handleSaveMemberAccess(
        memberIds: string[],
        resourceLevels: Partial<Record<APIScopeObject, AccessControlLevel | null>>
    ): Promise<void> {
        const accessControls = []

        for (const memberId of memberIds) {
            for (const [resource, level] of Object.entries(resourceLevels)) {
                accessControls.push({
                    resource: resource as APIScopeObject,
                    organization_member: memberId,
                    role: null,
                    access_level: level,
                })
            }
        }

        if (accessControls.length > 0) {
            updateResourceAccessControls(accessControls, 'member')
        }
    }

    async function handleSaveRoleAccess(
        roleIds: string[],
        resourceLevels: Partial<Record<APIScopeObject, AccessControlLevel | null>>
    ): Promise<void> {
        const accessControls = []

        for (const roleId of roleIds) {
            for (const [resource, level] of Object.entries(resourceLevels)) {
                accessControls.push({
                    resource: resource as APIScopeObject,
                    role: roleId,
                    organization_member: null,
                    access_level: level,
                })
            }
        }

        if (accessControls.length > 0) {
            updateResourceAccessControls(accessControls, 'role')
        }
    }
}

function ResourcesAccessControlMembers({
    memberResourceAccessControls,
    memberColumns,
    canEditRoleBasedAccessControls,
    openMemberModal,
}: {
    memberResourceAccessControls: MemberResourceAccessControls[]
    memberColumns: LemonTableColumns<MemberResourceAccessControls>
    canEditRoleBasedAccessControls: boolean | null
    openMemberModal: () => void
}): JSX.Element {
    return (
        <div className="space-y-2">
            <div className="flex gap-2 items-center justify-between">
                <h3 className="mb-0">Members</h3>
                <LemonButton
                    type="primary"
                    onClick={() => openMemberModal()}
                    disabledReason={!canEditRoleBasedAccessControls ? 'You cannot edit this' : undefined}
                >
                    Add
                </LemonButton>
            </div>
            {memberResourceAccessControls.length > 0 ? (
                <LemonTable columns={memberColumns} dataSource={memberResourceAccessControls} />
            ) : (
                <LemonTable columns={memberColumns} dataSource={[]} emptyState="No member specific permissions" />
            )}
        </div>
    )
}

function ResourcesAccessControlRoles({
    roleResourceAccessControls,
    roleColumns,
    canEditRoleBasedAccessControls,
    openRoleModal,
}: {
    roleResourceAccessControls: RoleResourceAccessControls[]
    roleColumns: LemonTableColumns<RoleResourceAccessControls>
    canEditRoleBasedAccessControls: boolean | null
    openRoleModal: () => void
}): JSX.Element {
    return (
        <div className="space-y-2">
            <div className="flex gap-2 items-center justify-between">
                <h3 className="mb-0">Roles</h3>
                <LemonButton
                    type="primary"
                    onClick={() => openRoleModal()}
                    disabledReason={!canEditRoleBasedAccessControls ? 'You cannot edit this' : undefined}
                >
                    Add
                </LemonButton>
            </div>
            {roleResourceAccessControls.length > 0 ? (
                <LemonTable columns={roleColumns} dataSource={roleResourceAccessControls} />
            ) : (
                <LemonTable columns={roleColumns} dataSource={[]} emptyState="No role specific permissions" />
            )}
        </div>
    )
}

function ResourceAccessControlModal(props: {
    modalOpen: boolean
    setModalOpen: () => void
    placeholder: string
    onSave: (
        newValues: string[],
        resourceLevels: Partial<Record<APIScopeObject, AccessControlLevel | null>>
    ) => Promise<void>
    options: {
        key: string
        label: string
        labelComponent?: JSX.Element
    }[]
    type: 'member' | 'role'
    editingEntry?: MemberResourceAccessControls | RoleResourceAccessControls | null
    loading?: boolean
}): JSX.Element | null {
    const { availableLevels, resources, canEditRoleBasedAccessControls } = useValues(resourcesAccessControlLogic)

    const isEditMode = !!props.editingEntry

    const [items, setItems] = useState<string[]>(() => {
        if (!isEditMode || !props.editingEntry) {
            return []
        }
        const editingId =
            props.type === 'member'
                ? (props.editingEntry as MemberResourceAccessControls).organization_member?.id
                : (props.editingEntry as RoleResourceAccessControls).role?.id
        return editingId ? [editingId] : []
    })

    const [resourceLevels, setResourceLevels] = useState<Partial<Record<APIScopeObject, AccessControlLevel | null>>>(
        () => {
            const levels: Partial<Record<APIScopeObject, AccessControlLevel | null>> = {}
            resources.forEach((resource) => {
                if (isEditMode && props.editingEntry) {
                    const ac = props.editingEntry?.accessControlByResource?.[resource]
                    levels[resource] = ac?.access_level ?? null
                } else {
                    levels[resource] = null
                }
            })
            return levels
        }
    )

    const isFormValid = useMemo(() => {
        return items.length > 0
    }, [items.length])

    const getValidationMessage = (): string | undefined => {
        if (!canEditRoleBasedAccessControls) {
            return 'You cannot edit this'
        }

        if (items.length === 0) {
            return `Please select ${props.type === 'member' ? 'members' : 'roles'} to configure`
        }

        return undefined
    }

    const onSubmit = isFormValid
        ? (): void => {
              props.onSave(items, resourceLevels)
          }
        : undefined

    // Update a specific resource's access level
    const updateResourceLevel = (resource: APIScopeObject, level: AccessControlLevel | null): void => {
        setResourceLevels((prev) => ({
            ...prev,
            [resource]: level,
        }))
    }

    // Create options for the access level dropdown
    const getLevelOptions = (): { value: AccessControlLevel | null; label: string }[] => {
        const options: { value: AccessControlLevel | null; label: string }[] = availableLevels.map((level) => ({
            value: level as AccessControlLevel,
            label: capitalizeFirstLetter(level ?? ''),
        }))

        // Add "No override" option
        options.push({
            value: null,
            label: 'No override',
        })

        return options
    }

    const getModalTitle = (): string => {
        if (isEditMode) {
            return props.type === 'member' ? 'Edit member resource access' : 'Edit role resource access'
        }
        return props.type === 'member' ? 'Configure member resource access' : 'Configure role resource access'
    }

    const getDisplayName = (): string | null => {
        if (!isEditMode || !props.editingEntry) {
            return null
        }

        if (props.type === 'member') {
            const member = (props.editingEntry as MemberResourceAccessControls).organization_member
            return member ? `${fullName(member.user)} (${member.user.email})` : null
        }
        const role = (props.editingEntry as RoleResourceAccessControls).role
        return role?.name ?? null
    }

    return (
        <LemonModal
            isOpen={props.modalOpen || false}
            onClose={props.loading ? undefined : props.setModalOpen}
            title={getModalTitle()}
            maxWidth="30rem"
            description={`Set resource access levels for ${props.type === 'member' ? 'members' : 'roles'}`}
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton type="secondary" onClick={props.setModalOpen} disabled={props.loading}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={onSubmit}
                        disabledReason={getValidationMessage()}
                        loading={props.loading}
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                {isEditMode ? (
                    <div className="font-medium">{getDisplayName()}</div>
                ) : (
                    <div className="flex gap-2 items-center w-full">
                        <div className="min-w-[16rem] w-full">
                            <LemonInputSelect
                                placeholder={props.placeholder}
                                value={items}
                                onChange={(newValues: string[]) => setItems(newValues)}
                                mode="multiple"
                                options={props.options}
                                disabled={!canEditRoleBasedAccessControls}
                            />
                        </div>
                    </div>
                )}

                <div className="space-y-2">
                    <div className="flex items-center justify-between">
                        <h5 className="mb-0">Resource access levels</h5>
                        <Link
                            to="#"
                            onClick={(e) => {
                                e.preventDefault()
                                if (!props.loading) {
                                    const cleared: Partial<Record<APIScopeObject, AccessControlLevel | null>> = {}
                                    for (const resource of resources) {
                                        cleared[resource] = null
                                    }
                                    setResourceLevels(cleared)
                                }
                            }}
                            className={props.loading ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}
                        >
                            Clear all
                        </Link>
                    </div>
                    {resources.map((resource) => (
                        <div key={resource} className="flex gap-2 items-center justify-between">
                            <div className="font-medium">{capitalizeFirstLetter(pluralizeResource(resource))}</div>
                            <div className="min-w-[8rem]">
                                <LemonSelect
                                    placeholder="No override"
                                    value={resourceLevels[resource]}
                                    onChange={(newValue) =>
                                        updateResourceLevel(resource, newValue as AccessControlLevel | null)
                                    }
                                    options={getLevelOptions()}
                                    disabled={!canEditRoleBasedAccessControls}
                                />
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </LemonModal>
    )
}

function DefaultResourceAccessControlModal(props: {
    modalOpen: boolean
    setModalOpen: () => void
    onSave: (resourceLevels: Partial<Record<APIScopeObject, AccessControlLevel | null>>) => Promise<void>
    defaultResourceAccessControls: DefaultResourceAccessControls
    loading?: boolean
}): JSX.Element | null {
    const { availableLevels, resources, canEditRoleBasedAccessControls } = useValues(resourcesAccessControlLogic)

    const [resourceLevels, setResourceLevels] = useState<Partial<Record<APIScopeObject, AccessControlLevel | null>>>(
        () => {
            const levels: Partial<Record<APIScopeObject, AccessControlLevel | null>> = {}
            resources.forEach((resource) => {
                const ac = props.defaultResourceAccessControls?.accessControlByResource?.[resource]
                levels[resource] = ac?.access_level ?? null
            })
            return levels
        }
    )

    const getValidationMessage = (): string | undefined => {
        if (!canEditRoleBasedAccessControls) {
            return 'You cannot edit this'
        }
        return undefined
    }

    const onSubmit = (): void => {
        props.onSave(resourceLevels)
    }

    const updateResourceLevel = (resource: APIScopeObject, level: AccessControlLevel | null): void => {
        setResourceLevels((prev) => ({
            ...prev,
            [resource]: level,
        }))
    }

    const getLevelOptions = (): { value: AccessControlLevel | null; label: string }[] => {
        const options: { value: AccessControlLevel | null; label: string }[] = availableLevels.map((level) => ({
            value: level as AccessControlLevel,
            label: capitalizeFirstLetter(level ?? ''),
        }))

        options.push({
            value: null,
            label: 'No override',
        })

        return options
    }

    return (
        <LemonModal
            isOpen={props.modalOpen || false}
            onClose={props.loading ? undefined : props.setModalOpen}
            title="Edit project defaults"
            maxWidth="30rem"
            description="Set default resource access levels for all roles and members"
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton type="secondary" onClick={props.setModalOpen} disabled={props.loading}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={onSubmit}
                        disabledReason={getValidationMessage()}
                        loading={props.loading}
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-2">
                <div className="flex items-center justify-between">
                    <h5 className="mb-0">Resource access levels</h5>
                    <Link
                        to="#"
                        onClick={(e) => {
                            e.preventDefault()
                            if (!props.loading) {
                                const cleared: Partial<Record<APIScopeObject, AccessControlLevel | null>> = {}
                                for (const resource of resources) {
                                    cleared[resource] = null
                                }
                                setResourceLevels(cleared)
                            }
                        }}
                        className={props.loading ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}
                    >
                        Clear all
                    </Link>
                </div>
                {resources.map((resource) => (
                    <div key={resource} className="flex gap-2 items-center justify-between">
                        <div className="font-medium">{capitalizeFirstLetter(pluralizeResource(resource))}</div>
                        <div className="min-w-[8rem]">
                            <LemonSelect
                                placeholder="No override"
                                value={resourceLevels[resource]}
                                onChange={(newValue) =>
                                    updateResourceLevel(resource, newValue as AccessControlLevel | null)
                                }
                                options={getLevelOptions()}
                                disabled={!canEditRoleBasedAccessControls}
                            />
                        </div>
                    </div>
                ))}
            </div>
        </LemonModal>
    )
}
