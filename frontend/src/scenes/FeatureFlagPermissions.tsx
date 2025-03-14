import { IconGear, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonInputSelect, LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { AccessControlPopoutCTA } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlPopoutCTA'
import { AccessControlResourceType, AccessLevel, AvailableFeature, FeatureFlagType, Resource, RoleType } from '~/types'

import { featureFlagPermissionsLogic } from './feature-flags/featureFlagPermissionsLogic'
import { permissionsLogic } from './settings/organization/Permissions/permissionsLogic'
import { rolesLogic } from './settings/organization/Permissions/Roles/rolesLogic'
import { teamLogic } from './teamLogic'
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

function roleLemonSelectOptions(roles: RoleType[]): LemonInputSelectOption[] {
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

export function FeatureFlagPermissions({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    const { addableRoles, unfilteredAddableRolesLoading, rolesToAdd, derivedRoles } = useValues(
        featureFlagPermissionsLogic({ flagId: featureFlag.id })
    )
    const { setRolesToAdd, addAssociatedRoles, deleteAssociatedRole } = useActions(
        featureFlagPermissionsLogic({ flagId: featureFlag.id })
    )
    const { currentTeam } = useValues(teamLogic)

    const newAccessControl = useFeatureFlag('ROLE_BASED_ACCESS_CONTROL')
    // Only render the new access control if they have been migrated and have the feature flag enabled
    if (newAccessControl && currentTeam?.access_control_version === 'v2') {
        if (!featureFlag.id) {
            return <p>Please save the feature flag before changing the access controls.</p>
        }
        return <AccessControlPopoutCTA resourceType={AccessControlResourceType.FeatureFlag} />
    }

    return (
        <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS}>
            <ResourcePermission
                resourceType={Resource.FEATURE_FLAGS}
                onChange={(roleIds) => setRolesToAdd(roleIds)}
                rolesToAdd={rolesToAdd}
                addableRoles={addableRoles}
                addableRolesLoading={unfilteredAddableRolesLoading}
                onAdd={() => addAssociatedRoles()}
                roles={derivedRoles}
                deleteAssociatedRole={(id) => deleteAssociatedRole({ roleId: id })}
                canEdit={featureFlag.can_edit}
            />
        </PayGateMini>
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
                                        to={`${urls.settings('organization-roles')}`}
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
