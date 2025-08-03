import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { organizationLogic } from 'scenes/organizationLogic'

import { AccessLevel, AvailableFeature, Resource, RoleType } from '~/types'

import { permissionsLogic } from './permissionsLogic'
import { CreateRoleModal } from './Roles/CreateRoleModal'
import { rolesLogic } from './Roles/rolesLogic'
import { getSingularType } from './utils'

export function PermissionsGrid(): JSX.Element {
    const { resourceRolesAccess, organizationResourcePermissionsLoading } = useValues(permissionsLogic)
    const { updatePermission } = useActions(permissionsLogic)
    const { roles, rolesLoading } = useValues(rolesLogic)
    const { setRoleInFocus, openCreateRoleModal } = useActions(rolesLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

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
                            <LemonButton noPadding onClick={() => setRoleInFocus(role)}>
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
                        <TitleWithIcon
                            icon={
                                <Tooltip title={`You can extend permissions on a per ${getSingularType(name)} basis.`}>
                                    <IconInfo />
                                </Tooltip>
                            }
                        >
                            <>
                                {name} <br /> Edit
                            </>
                        </TitleWithIcon>
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
                                    disabled={!isAdminOrOwner}
                                    color={isAdminOrOwner ? '' : 'gray'}
                                />
                            </div>
                        )
                    },
                },
            ]
        }) as LemonTableColumns<RoleType>),
    ]

    return (
        <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS}>
            <>
                <div className="flex flex-row justify-between items-center mb-4">
                    <div className="text-secondary-foreground">
                        Edit organizational default permission levels for PostHog resources. Use roles to apply
                        permissions to specific sets of users.
                    </div>
                </div>

                <LemonTable
                    columns={columns}
                    loading={rolesLoading || organizationResourcePermissionsLoading}
                    dataSource={[{ name: 'organization_default' } as RoleType, ...roles]}
                />

                <LemonButton
                    type="primary"
                    onClick={openCreateRoleModal}
                    className="mt-4"
                    data-attr="create-role-button"
                    disabledReason={restrictionReason}
                >
                    Create role
                </LemonButton>

                <CreateRoleModal />
            </>
        </PayGateMini>
    )
}
