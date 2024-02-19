import { IconGear, IconTrash } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTable } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import {
    LemonSelectMultiple,
    LemonSelectMultipleOptionItem,
} from 'lib/lemon-ui/LemonSelectMultiple/LemonSelectMultiple'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { AccessLevel, Resource, RoleType } from '~/types'

import {
    FormattedResourceLevel,
    permissionsLogic,
    ResourcePermissionMapping,
} from './settings/organization/Permissions/permissionsLogic'
import { rolesLogic } from './settings/organization/Permissions/Roles/rolesLogic'
import { urls } from './urls'

interface ResourcePermissionProps {
    addableRoles: RoleType[]
    addableRolesLoading: boolean
    onChange: (newValue: string[]) => void
    rolesToAdd: string[]
    onAdd: () => void
    roles: RoleType[]
    deleteAssociatedRole: (id: RoleType['id']) => void
    resourceType: Resource
    canEdit: boolean
}

interface ResourcePermissionModalProps extends ResourcePermissionProps {
    title: string
    visible: boolean
    onClose: () => void
}

export function roleLemonSelectOptions(roles: RoleType[]): LemonSelectMultipleOptionItem[] {
    return roles.map((role) => ({
        key: role.id,
        label: `${role.name}`,
        labelComponent: (
            <span>
                <b>{`${role.name}`}</b>
            </span>
        ),
    }))
}

export function ResourcePermissionModal({
    title,
    visible,
    onClose,
    rolesToAdd,
    addableRoles,
    onChange,
    addableRolesLoading,
    onAdd,
    roles,
    deleteAssociatedRole,
    canEdit,
}: ResourcePermissionModalProps): JSX.Element {
    return (
        <>
            <LemonModal title={title} isOpen={visible} onClose={onClose}>
                <ResourcePermission
                    resourceType={Resource.FEATURE_FLAGS}
                    onChange={onChange}
                    rolesToAdd={rolesToAdd}
                    addableRoles={addableRoles}
                    addableRolesLoading={addableRolesLoading}
                    onAdd={onAdd}
                    roles={roles}
                    deleteAssociatedRole={deleteAssociatedRole}
                    canEdit={canEdit}
                />
            </LemonModal>
        </>
    )
}

export function ResourcePermission({
    rolesToAdd,
    addableRoles,
    onChange,
    addableRolesLoading,
    onAdd,
    roles,
    deleteAssociatedRole,
    resourceType,
    canEdit,
}: ResourcePermissionProps): JSX.Element {
    const { allPermissions, shouldShowPermissionsTable } = useValues(permissionsLogic)
    const { roles: possibleRolesWithAccess } = useValues(rolesLogic)
    const resourceLevel = allPermissions.find((permission) => permission.resource === resourceType)
    // TODO: feature_flag_access_level should eventually be generic in this component
    const rolesWithAccess = possibleRolesWithAccess.filter(
        (role) => role.feature_flags_access_level === AccessLevel.WRITE
    )
    interface TableRoleType extends RoleType {
        deletable?: boolean
    }

    const columns: LemonTableColumns<TableRoleType> = [
        {
            title: 'Role',
            dataIndex: 'name',
            key: 'name',
            render: function RenderRoleName(_, role) {
                return (
                    <>
                        {role.name === 'Organization default' ? (
                            <TitleWithIcon
                                icon={
                                    <LemonButton
                                        icon={<IconGear />}
                                        to={`${urls.settings('organization')}?tab=role_based_access`}
                                        targetBlank
                                        size="small"
                                        noPadding
                                        tooltip="Organization-wide permissions for roles can be managed in the organization settings."
                                        className="ml-1"
                                    />
                                }
                            >
                                All users by default
                            </TitleWithIcon>
                        ) : (
                            role.name
                        )}
                    </>
                )
            },
        },
        {
            title: 'Access',
            dataIndex: 'feature_flags_access_level',
            key: 'feature_flags_access_level',
            render: function RenderAccessLevel(_, role) {
                return (
                    <div className="flex flex-row justify-between">
                        {role.feature_flags_access_level === AccessLevel.WRITE ? 'Edit' : 'View'}
                        {role.deletable && (
                            <LemonButton
                                icon={<IconTrash />}
                                onClick={() => deleteAssociatedRole(role.id)}
                                tooltip="Remove custom role from feature flag"
                                tooltipPlacement="bottomLeft"
                                size="small"
                            />
                        )}
                    </div>
                )
            },
        },
    ]
    const tableData: TableRoleType[] = [
        {
            id: '',
            name: 'Organization default',
            feature_flags_access_level: resourceLevel ? resourceLevel.access_level : AccessLevel.WRITE,
            created_by: null,
            created_at: '',
        } as TableRoleType,
        ...rolesWithAccess,
        ...roles.map((role) => ({ ...role, feature_flags_access_level: AccessLevel.WRITE, deletable: true })), // associated flag roles with custom write access
    ]

    return (
        <>
            {!shouldShowPermissionsTable && (
                <>
                    {resourceLevel && <OrganizationResourcePermissionLabel resourceLevel={resourceLevel} />}
                    <OrganizationResourcePermissionRoles roles={rolesWithAccess} />
                </>
            )}
            {shouldShowPermissionsTable && <LemonTable dataSource={tableData} columns={columns} className="mt-4" />}
            {!shouldShowPermissionsTable && (
                <>
                    <h5 className="mt-4">Roles</h5>
                    {roles.length > 0 ? (
                        <div className="pb-2 rounded overflow-y-auto max-h-80">
                            {roles.map((role) => {
                                return (
                                    <RoleRow
                                        key={role.id}
                                        role={role}
                                        deleteRole={(roleId) => deleteAssociatedRole(roleId)}
                                    />
                                )
                            })}
                        </div>
                    ) : (
                        <div className="text-muted mb-2">No roles added yet</div>
                    )}
                </>
            )}
            {canEdit && (
                <>
                    <h5 className="mt-4">Custom edit roles</h5>
                    <div className="flex gap-2">
                        <div className="flex-1">
                            <LemonSelectMultiple
                                placeholder="Search for roles to add…"
                                loading={addableRolesLoading}
                                onChange={onChange}
                                value={rolesToAdd}
                                filterOption={true}
                                mode="multiple"
                                data-attr="resource-permissioning-select"
                                options={roleLemonSelectOptions(addableRoles)}
                            />
                        </div>
                        <LemonButton type="primary" loading={false} disabled={rolesToAdd.length === 0} onClick={onAdd}>
                            Add
                        </LemonButton>
                    </div>
                </>
            )}
        </>
    )
}

function OrganizationResourcePermissionLabel({
    resourceLevel,
}: {
    resourceLevel: FormattedResourceLevel
}): JSX.Element {
    return (
        <>
            <TitleWithIcon
                icon={
                    <LemonButton
                        icon={<IconGear />}
                        to={`${urls.settings('organization')}?tab=role_based_access`}
                        targetBlank
                        size="small"
                        noPadding
                        className="ml-1"
                    />
                }
            >
                <h5>Organization default</h5>
            </TitleWithIcon>
            <b>{ResourcePermissionMapping[resourceLevel.access_level]}</b>
        </>
    )
}

function OrganizationResourcePermissionRoles({ roles }: { roles: RoleType[] }): JSX.Element {
    return (
        <>
            <h5 className="mt-4">Roles with edit access</h5>
            <div className="flex">
                {roles.map((role) => (
                    <span key={role.id} className="simple-tag tag-light-blue text-primary-alt mr-2">
                        <b>{role.name}</b>{' '}
                    </span>
                ))}
            </div>
        </>
    )
}

function RoleRow({ role, deleteRole }: { role: RoleType; deleteRole?: (roleId: RoleType['id']) => void }): JSX.Element {
    return (
        <div className="flex items-center justify-between h-8">
            <b>{role.name}</b>
            {deleteRole && (
                <LemonButton
                    icon={<IconTrash />}
                    onClick={() => deleteRole(role.id)}
                    tooltip="Remove role from permission"
                    tooltipPlacement="bottomLeft"
                    size="small"
                />
            )}
        </div>
    )
}
