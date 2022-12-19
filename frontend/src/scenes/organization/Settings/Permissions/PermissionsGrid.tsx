import { LemonButton, LemonCheckbox, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonTableColumns } from 'lib/components/LemonTable'
import { RestrictedComponentProps } from 'lib/components/RestrictedArea'
import { Tooltip } from 'lib/components/Tooltip'
import { AccessLevel, Resource, RoleType } from '~/types'
import { permissionsLogic } from './permissionsLogic'
import { CreateRoleModal } from './Roles/CreateRoleModal'
import { rolesLogic } from './Roles/rolesLogic'

export function PermissionsGrid({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { resourceRolesAccess, organizationResourcePermissionsLoading } = useValues(permissionsLogic)
    const { updatePermission } = useActions(permissionsLogic)
    const { roles, rolesLoading } = useValues(rolesLogic)
    const { setRoleInFocus, openCreateRoleModal } = useActions(rolesLogic)
    const columns: LemonTableColumns<RoleType> = [
        {
            key: 'role',
            title: '',
            width: 150,
            render: function RenderRole(_, role) {
                return (
                    <>
                        {role.name == 'organization_default' ? (
                            <b>All users by default</b>
                        ) : (
                            <LemonButton type="tertiary" noPadding onClick={() => setRoleInFocus(role)}>
                                {role.name}
                            </LemonButton>
                        )}
                    </>
                )
            },
        },
        ...(resourceRolesAccess.flatMap((resource) => {
            const name = Object.keys(resource)[0] as Resource
            return [
                {
                    key: 'view',
                    title: (
                        <Tooltip title="View defaults cannot be changed">
                            <div className="text-center">
                                {name} <br /> View
                            </div>
                        </Tooltip>
                    ),
                    align: 'center',
                    render: function RenderView() {
                        return (
                            <div className="flex justify-center">
                                <LemonCheckbox defaultChecked disabled color="gray" />
                            </div>
                        )
                    },
                },
                {
                    key: 'edit',
                    title: (
                        <div className="text-center">
                            {name} <br /> Edit
                        </div>
                    ),
                    align: 'center',
                    render: function RenderEdit(_, role) {
                        return (
                            <div className="flex justify-center">
                                <LemonCheckbox
                                    onChange={(v) => {
                                        updatePermission(v, role, resource[name].id, name)
                                    }}
                                    checked={resource[`${name}`][role.name] >= AccessLevel.WRITE}
                                />
                            </div>
                        )
                    },
                },
            ]
        }) as LemonTableColumns<RoleType>),
    ]

    return (
        <>
            <div className="flex flex-row justify-between items-center mb-4">
                <div className="text-muted-alt">
                    Edit organizational default permission levels for posthog resources. Use roles to apply permissions
                    to specific sets of users.
                </div>
                {!isRestricted && (
                    <LemonButton type="primary" onClick={openCreateRoleModal} data-attr="create-role-button">
                        Create role
                    </LemonButton>
                )}
            </div>
            <LemonTable
                bordered
                columns={columns}
                loading={rolesLoading || organizationResourcePermissionsLoading}
                dataSource={[{ name: 'organization_default' } as RoleType, ...roles]}
            />
            <CreateRoleModal />
        </>
    )
}
