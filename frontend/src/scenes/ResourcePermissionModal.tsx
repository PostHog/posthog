import { LemonButton, LemonDivider, LemonModal } from '@posthog/lemon-ui'
import { Row } from 'antd'
import { useValues } from 'kea'
import { IconDelete } from 'lib/components/icons'
import {
    LemonSelectMultiple,
    LemonSelectMultipleOptionItem,
} from 'lib/components/LemonSelectMultiple/LemonSelectMultiple'
import { AccessLevel, Resource, RoleType } from '~/types'
import {
    FormattedResourceLevel,
    permissionsLogic,
    ResourcePermissionMapping,
} from './organization/Settings/Permissions/permissionsLogic'
import { rolesLogic } from './organization/Settings/Roles/rolesLogic'
import { organizationLogic } from './organizationLogic'

interface ResourcePermissionModalProps {
    title: string
    visible: boolean
    onClose: () => void
    addableRoles: RoleType[]
    addableRolesLoading: boolean
    onChange: (newValue: string[]) => void
    rolesToAdd: string[]
    onAdd: () => void
    roles: RoleType[]
    deleteAssociatedRole: (id: RoleType['id']) => void
    isNewResource: boolean
    resourceType: Resource
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
    resourceType,
}: ResourcePermissionModalProps): JSX.Element {
    const { allPermissions } = useValues(permissionsLogic)
    const { roles: possibleRolesWithAccess } = useValues(rolesLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)

    const resourceLevel = allPermissions.find((permission) => permission.resource === resourceType)

    // TODO: feature_flag_access_level should eventually be generic in this component
    const rolesWithAccess = possibleRolesWithAccess.filter(
        (role) => role.feature_flags_access_level === AccessLevel.WRITE
    )

    return (
        <LemonModal title={title} isOpen={visible} onClose={onClose}>
            {resourceLevel && <OrganizationResourcePermissionLabel resourceLevel={resourceLevel} />}
            {<OrganizationResourcePermissionRoles roles={rolesWithAccess} />}
            {isAdminOrOwner && (
                <>
                    <LemonDivider className="mt-4" />
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
            {!isNewResource && (
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
        </LemonModal>
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
            <b>{ResourcePermissionMapping[resourceLevel.access_level]}</b>
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
                        {role.name}{' '}
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
