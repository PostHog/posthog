import { IconGear, IconTrash } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTable } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { LemonInputSelect, LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { AccessLevel, Resource, RoleType } from '~/types'

import { permissionsLogic } from './settings/organization/Permissions/permissionsLogic'
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

export function roleLemonSelectOptions(roles: RoleType[]): LemonInputSelectOption[] {
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
    const { allPermissions } = useValues(permissionsLogic)
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
                                        to={`${urls.settings('organization-rbac')}`}
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
                                tooltipPlacement="bottom-start"
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
            <LemonTable dataSource={tableData} columns={columns} className="mt-4" />
            {canEdit && (
                <>
                    <h5 className="mt-4">Custom edit roles</h5>
                    <div className="flex gap-2">
                        <div className="flex-1">
                            <LemonInputSelect
                                placeholder="Search for roles to add…"
                                loading={addableRolesLoading}
                                onChange={onChange}
                                value={rolesToAdd}
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
