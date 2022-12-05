import { LemonButton, LemonModal, LemonTable, Link } from '@posthog/lemon-ui'
import { Row } from 'antd'
import { useValues } from 'kea'
import { IconDelete } from 'lib/components/icons'
import {
    LemonSelectMultiple,
    LemonSelectMultipleOptionItem,
} from 'lib/components/LemonSelectMultiple/LemonSelectMultiple'
import { LemonTableColumns } from 'lib/components/LemonTable'
import { AccessLevel, Resource, RoleType } from '~/types'
import {
    FormattedResourceLevel,
    permissionsLogic,
    ResourcePermissionMapping,
} from './organization/Settings/Permissions/permissionsLogic'
import { rolesLogic } from './organization/Settings/Roles/rolesLogic'
import { urls } from './urls'

interface ResourcePermissionProps {
    addableRoles: RoleType[]
    addableRolesLoading: boolean
    onChange: (newValue: string[]) => void
    rolesToAdd: string[]
    onAdd: () => void
    roles: RoleType[]
    deleteAssociatedRole: (id: RoleType['id']) => void
    isNewResource: boolean
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
    isNewResource,
    canEdit,
}: ResourcePermissionModalProps): JSX.Element {
    return (
        <>
            <LemonModal title={title} isOpen={visible} onClose={onClose}>
                <ResourcePermission
                    resourceType={Resource.FEATURE_FLAGS}
                    isNewResource={isNewResource}
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
    isNewResource,
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
                            <Link to={`${urls.organizationSettings()}?tab=role_access`}>{role.name}</Link>
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
                                icon={<IconDelete />}
                                onClick={() => deleteAssociatedRole(role.id)}
                                tooltip={'Remove custom role from feature flag'}
                                status="primary-alt"
                                type="tertiary"
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
                    {<OrganizationResourcePermissionRoles roles={rolesWithAccess} />}
                </>
            )}
            {(isNewResource || canEdit) && (
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
                        {!isNewResource && (
                            <LemonButton
                                type="primary"
                                loading={false}
                                disabled={rolesToAdd.length === 0}
                                onClick={onAdd}
                            >
                                Add
                            </LemonButton>
                        )}
                    </div>
                </>
            )}
            {shouldShowPermissionsTable && <LemonTable dataSource={tableData} columns={columns} className="mt-4" />}
            {!shouldShowPermissionsTable && !isNewResource && (
                <>
                    <h5 className="mt-4">Roles</h5>
                    {roles.length > 0 ? (
                        <div
                            className="pb-2 rounded overflow-y-auto"
                            style={{
                                maxHeight: 300,
                            }}
                        >
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
            <h5>Organization Default</h5>
            <Link to={`${urls.organizationSettings()}?tab=role_access`}>
                <b>{ResourcePermissionMapping[resourceLevel.access_level]}</b>
            </Link>
        </>
    )
}

function OrganizationResourcePermissionRoles({ roles }: { roles: RoleType[] }): JSX.Element {
    return (
        <>
            <h5 className="mt-4">Roles with edit access</h5>
            <Row>
                {roles.map((role) => (
                    <span key={role.id} className="simple-tag tag-light-blue text-primary-alt">
                        <b>{role.name}</b>{' '}
                    </span>
                ))}
            </Row>
        </>
    )
}

function RoleRow({ role, deleteRole }: { role: RoleType; deleteRole?: (roleId: RoleType['id']) => void }): JSX.Element {
    return (
        <div className="flex items-center justify-between h-8">
            <b>{role.name}</b>
            {deleteRole && (
                <LemonButton
                    icon={<IconDelete />}
                    onClick={() => deleteRole(role.id)}
                    tooltip={'Remove role from permission'}
                    status="primary-alt"
                    type="tertiary"
                    size="small"
                />
            )}
        </div>
    )
}
