import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { organizationLogic } from 'scenes/organizationLogic'
import { AccessLevel } from '~/types'
import { permissionsLogic, FormattedResourceLevel, ResourcePermissionMapping } from './permissionsLogic'

export function Permissions(): JSX.Element {
    const { allPermissions } = useValues(permissionsLogic)
    const { updateOrganizationResourcePermission } = useActions(permissionsLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)

    const columns: LemonTableColumns<FormattedResourceLevel> = [
        {
            key: 'name',
            title: 'Resource',
            dataIndex: 'name',
            render: function RenderResource(_, permission) {
                return <b>{permission.resource}</b>
            },
        },
        {
            key: 'access_level',
            title: 'Access Level',
            dataIndex: 'access_level',
            render: function RenderAccessLevel(_, permission) {
                return (
                    <LemonSelect
                        disabled={!isAdminOrOwner}
                        value={permission.access_level}
                        onChange={(newValue) =>
                            updateOrganizationResourcePermission({
                                id: permission.id,
                                resource: permission.resource,
                                access_level: newValue,
                            })
                        }
                        options={[
                            {
                                value: AccessLevel.WRITE,
                                label: ResourcePermissionMapping[AccessLevel.WRITE],
                            },
                            {
                                value: AccessLevel.READ,
                                label: ResourcePermissionMapping[AccessLevel.READ],
                            },
                            {
                                value: AccessLevel.CUSTOM_ASSIGNED,
                                label: ResourcePermissionMapping[AccessLevel.CUSTOM_ASSIGNED],
                            },
                        ]}
                    />
                )
            },
        },
    ]

    return (
        <>
            <div className="flex items-center">
                <div style={{ flexGrow: 1 }}>
                    <h2 id="roles" className="subtitle">
                        Permission Defaults
                    </h2>
                    <p className="text-muted-alt">
                        Add default permission levels for posthog resources. Use roles to apply permissions to specific
                        sets of users.
                    </p>
                </div>
            </div>
            <LemonTable
                dataSource={allPermissions}
                columns={columns}
                rowKey={() => 'id'}
                style={{ marginTop: '1rem' }}
                loading={false}
                data-attr="org-permissions-table"
                defaultSorting={{ columnKey: 'level', order: -1 }}
                pagination={{ pageSize: 50 }}
            />
        </>
    )
}
