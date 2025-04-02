import { LemonSelect, LemonTable, LemonTableColumns, ProfileBubbles } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'kea-forms'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

import { AccessControlLevel, AvailableFeature } from '~/types'

import { roleBasedAccessControlLogic, RoleWithResourceAccessControls } from './roleBasedAccessControlLogic'

export function ResourcesAccessControls(): JSX.Element {
    const {
        rolesWithResourceAccessControls,
        rolesLoading,
        roleBasedAccessControlsLoading,
        resources,
        availableLevels,
        defaultAccessLevel,
    } = useValues(roleBasedAccessControlLogic)

    const { updateRoleBasedAccessControls } = useActions(roleBasedAccessControlLogic)

    const roleColumns = resources.map((resource) => ({
        title: resource.replace(/_/g, ' ') + 's',
        key: resource,
        width: 0,
        render: (_: any, { accessControlByResource, role }: RoleWithResourceAccessControls) => {
            const ac = accessControlByResource[resource]

            const options: { value: string | null; label: string }[] = availableLevels.map((level) => ({
                value: level,
                label: capitalizeFirstLetter(level ?? ''),
            }))

            if (role?.id) {
                options.push({
                    value: null,
                    label: 'No override',
                })
            }

            return (
                <LemonSelect
                    size="small"
                    placeholder="No override"
                    className="my-1 whitespace-nowrap"
                    value={role ? ac?.access_level : ac?.access_level ?? defaultAccessLevel}
                    onChange={(newValue) =>
                        updateRoleBasedAccessControls([
                            {
                                resource,
                                role: role?.id ?? null,
                                access_level: newValue as AccessControlLevel | null,
                            },
                        ])
                    }
                    options={options}
                />
            )
        },
    }))

    const columns: LemonTableColumns<RoleWithResourceAccessControls> = [
        {
            title: 'Role',
            key: 'role',
            width: 0,
            render: (_, { role }) => <span className="whitespace-nowrap">{role?.name ?? 'Default'}</span>,
        },
        {
            title: 'Members',
            key: 'members',
            render: (_, { role }) => {
                return role ? (
                    role.members.length ? (
                        <ProfileBubbles
                            people={role.members.map((member) => ({
                                email: member.user.email,
                                name: member.user.first_name,
                                title: `${member.user.first_name} <${member.user.email}>`,
                            }))}
                        />
                    ) : (
                        'No members'
                    )
                ) : (
                    'All members'
                )
            },
        },

        ...roleColumns,
    ]

    return (
        <div className="deprecated-space-y-2">
            <h2>Resource permissions</h2>
            <p>
                Use resource permissions to assign project-wide access to specific resources for individuals and roles.
            </p>

            <PayGateMini feature={AvailableFeature.ADVANCED_PERMISSIONS}>
                <div className="deprecated-space-y-2">
                    <LemonTable
                        columns={columns}
                        dataSource={rolesWithResourceAccessControls}
                        loading={rolesLoading || roleBasedAccessControlsLoading}
                    />
                </div>
            </PayGateMini>
        </div>
    )
}
