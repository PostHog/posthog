import {
    LemonButton,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    ProfileBubbles,
    ProfilePicture,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'kea-forms'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { UserSelectItem } from 'lib/components/UserSelectItem'
import { useEffect, useMemo, useState } from 'react'
import { fullName } from 'lib/utils'

import { AccessControlLevel, APIScopeObject, AvailableFeature, OrganizationMemberType, RoleType } from '~/types'

import {
    DefaultResourceAccessControls,
    MemberResourceAccessControls,
    resourcesAccessControlLogic,
    RoleResourceAccessControls,
} from './resourcesAccessControlLogic'

export function ResourcesAccessControls(): JSX.Element {
    const {
        defaultResourceAccessControls,
        memberResourceAccessControls,
        roleResourceAccessControls,
        resources,
        availableLevels,
        canEditRoleBasedAccessControls,
        addableMembers,
        addableRoles,
    } = useValues(resourcesAccessControlLogic)
    const { updateResourceAccessControls } = useActions(resourcesAccessControlLogic)

    // State for the modals
    const [memberModalOpen, setMemberModalOpen] = useState(false)
    const [roleModalOpen, setRoleModalOpen] = useState(false)

    // Default table
    const defaultColumns: LemonTableColumns<DefaultResourceAccessControls> = [
        {
            title: '',
            key: 'default',
            width: 0,
            render: () => 'All roles and members',
        },
        ...createDefaultResourceColumns(),
    ]

    // Members table
    const memberColumns: LemonTableColumns<MemberResourceAccessControls> = [
        {
            title: 'User',
            key: 'member',
            width: 0,
            render: (_, { organization_member }) => {
                // organization_member is guaranteed to exist in MemberResourceAccessControls
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
        ...createMemberResourceColumns(),
    ]

    // Roles table
    const roleColumns: LemonTableColumns<RoleResourceAccessControls> = [
        {
            title: 'Role',
            key: 'role',
            width: 0,
            render: (_, { role }) => {
                // role is guaranteed to exist in RoleResourceAccessControls
                return <span>{role!.name}</span>
            },
        },
        {
            title: 'Members',
            key: 'members',
            width: 0,
            render: (_, { role }) => {
                // role is guaranteed to exist in RoleResourceAccessControls
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
        ...createRoleResourceColumns(),
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
                        setMemberModalOpen={setMemberModalOpen}
                    />

                    <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS}>
                        {/* Roles permissions table */}
                        <ResourcesAccessControlRoles
                            roleResourceAccessControls={roleResourceAccessControls}
                            roleColumns={roleColumns}
                            canEditRoleBasedAccessControls={canEditRoleBasedAccessControls}
                            setRoleModalOpen={setRoleModalOpen}
                        />
                    </PayGateMini>
                </div>
            </PayGateMini>

            {/* Modals for adding access controls */}
            <AddResourceAccessControlModal
                modalOpen={memberModalOpen}
                setModalOpen={setMemberModalOpen}
                placeholder="Search for team members to add…"
                onAdd={handleAddMemberAccess}
                options={addableMembers.map((member) => ({
                    key: member.id,
                    label: `${fullName(member.user)} ${member.user.email}`,
                    labelComponent: <UserSelectItem user={member.user} />,
                }))}
                type="member"
            />

            <AddResourceAccessControlModal
                modalOpen={roleModalOpen}
                setModalOpen={setRoleModalOpen}
                placeholder="Search for roles to add…"
                onAdd={handleAddRoleAccess}
                options={addableRoles.map((role) => ({
                    key: role.id,
                    label: role.name,
                }))}
                type="role"
            />
        </div>
    )

    // Generic function to create resource columns for a specific type
    function createResourceColumnsForType<T extends DefaultResourceAccessControls>(
        getRole: (item: T) => RoleType | undefined,
        getMember: (item: T) => OrganizationMemberType | undefined
    ): LemonTableColumns<T> {
        return resources.map((resource: APIScopeObject) => ({
            title: resource.replace(/_/g, ' ') + 's',
            key: resource,
            width: 0,
            render: (_: any, item: T) => {
                const { accessControlByResource } = item
                const role = getRole(item)
                const organization_member = getMember(item)
                const ac = accessControlByResource[resource]

                const options: { value: string | null; label: string }[] = availableLevels.map(
                    (level: AccessControlLevel) => ({
                        value: level,
                        label: capitalizeFirstLetter(level ?? ''),
                    })
                )
                options.push({
                    value: null,
                    label: 'No override',
                })

                return (
                    <LemonSelect
                        size="small"
                        placeholder="No override"
                        className="my-1 whitespace-nowrap"
                        value={ac?.access_level}
                        onChange={(newValue) =>
                            updateResourceAccessControls([
                                {
                                    resource,
                                    role: role?.id ?? null,
                                    organization_member: organization_member?.id ?? null,
                                    access_level: newValue as AccessControlLevel | null,
                                },
                            ])
                        }
                        options={options}
                        disabledReason={canEditRoleBasedAccessControls ? undefined : 'You cannot edit this'}
                    />
                )
            },
        }))
    }

    // Create specific column creators for each table type
    function createDefaultResourceColumns(): LemonTableColumns<DefaultResourceAccessControls> {
        return createResourceColumnsForType<DefaultResourceAccessControls>(
            () => undefined,
            () => undefined
        )
    }

    function createMemberResourceColumns(): LemonTableColumns<MemberResourceAccessControls> {
        return createResourceColumnsForType<MemberResourceAccessControls>(
            () => undefined,
            (item: MemberResourceAccessControls) => item.organization_member
        )
    }

    function createRoleResourceColumns(): LemonTableColumns<RoleResourceAccessControls> {
        return createResourceColumnsForType<RoleResourceAccessControls>(
            (item: RoleResourceAccessControls) => item.role,
            () => undefined
        )
    }

    // Function to handle adding a member access control
    function handleAddMemberAccess(
        memberIds: string[],
        resourceLevels: Partial<Record<APIScopeObject, AccessControlLevel | null>>
    ): Promise<void> {
        const accessControls = []

        for (const memberId of memberIds) {
            for (const [resource, level] of Object.entries(resourceLevels)) {
                // Only add entries where a level is explicitly set (not null)
                if (level !== null) {
                    accessControls.push({
                        resource: resource as APIScopeObject,
                        organization_member: memberId,
                        role: null,
                        access_level: level,
                    })
                }
            }
        }

        if (accessControls.length > 0) {
            updateResourceAccessControls(accessControls)
        }
        setMemberModalOpen(false)
        return Promise.resolve()
    }

    // Function to handle adding a role access control
    function handleAddRoleAccess(
        roleIds: string[],
        resourceLevels: Partial<Record<APIScopeObject, AccessControlLevel | null>>
    ): Promise<void> {
        const accessControls = []

        for (const roleId of roleIds) {
            for (const [resource, level] of Object.entries(resourceLevels)) {
                // Only add entries where a level is explicitly set (not null)
                if (level !== null) {
                    accessControls.push({
                        resource: resource as APIScopeObject,
                        role: roleId,
                        organization_member: null,
                        access_level: level,
                    })
                }
            }
        }

        if (accessControls.length > 0) {
            updateResourceAccessControls(accessControls)
        }
        setRoleModalOpen(false)
        return Promise.resolve()
    }
}

function ResourcesAccessControlMembers({
    memberResourceAccessControls,
    memberColumns,
    canEditRoleBasedAccessControls,
    setMemberModalOpen,
}: {
    memberResourceAccessControls: MemberResourceAccessControls[]
    memberColumns: LemonTableColumns<MemberResourceAccessControls>
    canEditRoleBasedAccessControls: boolean | null
    setMemberModalOpen: (open: boolean) => void
}): JSX.Element {
    return (
        <div className="space-y-2">
            <div className="flex gap-2 items-center justify-between">
                <h3 className="mb-0">Members</h3>
                <LemonButton
                    type="primary"
                    onClick={() => setMemberModalOpen(true)}
                    disabledReason={!canEditRoleBasedAccessControls ? 'You cannot edit this' : undefined}
                >
                    Add
                </LemonButton>
            </div>
            {memberResourceAccessControls.length > 0 ? (
                <LemonTable columns={memberColumns} dataSource={memberResourceAccessControls} />
            ) : (
                <LemonTable columns={memberColumns} dataSource={[]} emptyState="No entries" />
            )}
        </div>
    )
}

function ResourcesAccessControlRoles({
    roleResourceAccessControls,
    roleColumns,
    canEditRoleBasedAccessControls,
    setRoleModalOpen,
}: {
    roleResourceAccessControls: RoleResourceAccessControls[]
    roleColumns: LemonTableColumns<RoleResourceAccessControls>
    canEditRoleBasedAccessControls: boolean | null
    setRoleModalOpen: (open: boolean) => void
}): JSX.Element {
    return (
        <div className="space-y-2">
            <div className="flex gap-2 items-center justify-between">
                <h3 className="mb-0">Roles</h3>
                <LemonButton
                    type="primary"
                    onClick={() => setRoleModalOpen(true)}
                    disabledReason={!canEditRoleBasedAccessControls ? 'You cannot edit this' : undefined}
                >
                    Add
                </LemonButton>
            </div>
            {roleResourceAccessControls.length > 0 ? (
                <LemonTable columns={roleColumns} dataSource={roleResourceAccessControls} />
            ) : (
                <LemonTable columns={roleColumns} dataSource={[]} emptyState="No entries" />
            )}
        </div>
    )
}

function AddResourceAccessControlModal(props: {
    modalOpen: boolean
    setModalOpen: (open: boolean) => void
    placeholder: string
    onAdd: (
        newValues: string[],
        resourceLevels: Partial<Record<APIScopeObject, AccessControlLevel | null>>
    ) => Promise<void>
    options: {
        key: string
        label: string
        labelComponent?: JSX.Element
    }[]
    type: 'member' | 'role'
}): JSX.Element | null {
    const { availableLevels, resources, canEditRoleBasedAccessControls } = useValues(resourcesAccessControlLogic)

    const [items, setItems] = useState<string[]>([])
    const [resourceLevels, setResourceLevels] = useState<Partial<Record<APIScopeObject, AccessControlLevel | null>>>({})

    useEffect(() => {
        if (resources.length > 0) {
            const initialResourceLevels: Partial<Record<APIScopeObject, AccessControlLevel | null>> = {}

            resources.forEach((resource) => {
                initialResourceLevels[resource] = null // Default to "No override"
            })

            setResourceLevels(initialResourceLevels)
        }
    }, [resources])

    // Check if at least one resource has an access level set
    const hasAtLeastOneResourceLevel = useMemo(() => {
        return Object.values(resourceLevels).some((level) => level !== null)
    }, [resourceLevels])

    // Determine if the form is valid and can be submitted
    const isFormValid = useMemo(() => {
        return items.length > 0 && hasAtLeastOneResourceLevel
    }, [items.length, hasAtLeastOneResourceLevel])

    // Get validation message if form is invalid
    const getValidationMessage = (): string | undefined => {
        if (!canEditRoleBasedAccessControls) {
            return 'You cannot edit this'
        }

        if (items.length === 0) {
            return `Please select ${props.type === 'member' ? 'members' : 'roles'} to configure`
        }

        if (!hasAtLeastOneResourceLevel) {
            return 'Please set at least one resource access level'
        }

        return undefined
    }

    const onSubmit = isFormValid
        ? (): void =>
              void props.onAdd(items, resourceLevels).then(() => {
                  setItems([])
                  // Reset resource levels to defaults (null for "No override")
                  if (resources.length > 0) {
                      const resetResourceLevels: Partial<Record<APIScopeObject, AccessControlLevel | null>> = {}
                      resources.forEach((resource) => {
                          resetResourceLevels[resource] = null // Reset to "No override"
                      })
                      setResourceLevels(resetResourceLevels)
                  }
              })
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

    // Get appropriate title based on the type (member or role)
    const getModalTitle = (): string => {
        return props.type === 'member' ? 'Configure member resource access' : 'Configure role resource access'
    }

    return (
        <LemonModal
            isOpen={props.modalOpen || false}
            onClose={() => props.setModalOpen(false)}
            title={getModalTitle()}
            maxWidth="30rem"
            description={`Set resource access levels for ${props.type === 'member' ? 'members' : 'roles'}`}
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton type="secondary" onClick={() => props.setModalOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={onSubmit} disabledReason={getValidationMessage()}>
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
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

                <div className="space-y-2">
                    <h5 className="mb-2">Resource access levels</h5>
                    {resources.map((resource) => (
                        <div key={resource} className="flex gap-2 items-center justify-between">
                            <div className="font-medium">
                                {capitalizeFirstLetter(resource?.replace(/_/g, ' ') ?? '') + 's'}
                            </div>
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
