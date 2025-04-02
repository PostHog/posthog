import { LemonSelect, LemonTable, LemonTableColumns, ProfileBubbles, ProfilePicture } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'kea-forms'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

import { AccessControlLevel, AvailableFeature, OrganizationMemberType, RoleType } from '~/types'

import {
    DefaultResourceAccessControls,
    MemberResourceAccessControls,
    roleBasedAccessControlLogic,
    RoleResourceAccessControls,
} from './roleBasedAccessControlLogic'

export function ResourcesAccessControls(): JSX.Element {
    const {
        defaultResourceAccessControls,
        memberResourceAccessControls,
        roleResourceAccessControls,
        rolesLoading,
        resources,
        availableLevels,
        defaultAccessLevel,
    } = useValues(roleBasedAccessControlLogic)

    const { updateResourceAccessControls } = useActions(roleBasedAccessControlLogic)

    // Generic function to create resource columns for a specific type
    const createResourceColumnsForType = <T extends DefaultResourceAccessControls>(
        showNoOverride: boolean = false,
        getRole: (item: T) => RoleType | undefined,
        getMember: (item: T) => OrganizationMemberType | undefined
    ): LemonTableColumns<T> =>
        resources.map((resource) => ({
            title: resource.replace(/_/g, ' ') + 's',
            key: resource,
            width: 0,
            render: (_: any, item: T) => {
                const { accessControlByResource } = item
                const role = getRole(item)
                const organization_member = getMember(item)
                const ac = accessControlByResource[resource]

                const options: { value: string | null; label: string }[] = availableLevels.map((level) => ({
                    value: level,
                    label: capitalizeFirstLetter(level ?? ''),
                }))

                if (showNoOverride) {
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
                        value={role || organization_member ? ac?.access_level : ac?.access_level ?? defaultAccessLevel}
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
                    />
                )
            },
        }))

    // Create specific column creators for each table type
    const createDefaultResourceColumns = (): LemonTableColumns<DefaultResourceAccessControls> =>
        createResourceColumnsForType<DefaultResourceAccessControls>(
            false,
            () => undefined,
            () => undefined
        )

    const createMemberResourceColumns = (
        showNoOverride: boolean = false
    ): LemonTableColumns<MemberResourceAccessControls> =>
        createResourceColumnsForType<MemberResourceAccessControls>(
            showNoOverride,
            () => undefined,
            (item) => item.organization_member
        )

    const createRoleResourceColumns = (
        showNoOverride: boolean = false
    ): LemonTableColumns<RoleResourceAccessControls> =>
        createResourceColumnsForType<RoleResourceAccessControls>(
            showNoOverride,
            (item) => item.role,
            () => undefined
        )

    // Default table
    const defaultColumns: LemonTableColumns<DefaultResourceAccessControls> = [
        {
            title: 'Global Defaults',
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
                            <p className="font-medium mb-0">{organization_member!.user.first_name}</p>
                            <p className="text-secondary mb-0">{organization_member!.user.email}</p>
                        </div>
                    </div>
                )
            },
        },
        ...createMemberResourceColumns(true),
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
                                people={role!.members.map((member) => ({
                                    email: member.user.email,
                                    name: member.user.first_name,
                                    title: `${member.user.first_name} <${member.user.email}>`,
                                }))}
                            />
                        ) : (
                            'No members'
                        )}
                    </div>
                )
            },
        },
        ...createRoleResourceColumns(true),
    ]

    return (
        <div className="space-y-4">
            <h2>Resource permissions</h2>
            <p>
                Use resource permissions to assign project-wide access to specific resources for individuals and roles.
            </p>

            <PayGateMini feature={AvailableFeature.ADVANCED_PERMISSIONS}>
                <div className="space-y-6">
                    {/* Default permissions table */}
                    <div>
                        <h3>Global defaults</h3>
                        <LemonTable
                            columns={defaultColumns}
                            dataSource={[defaultResourceAccessControls]}
                            loading={rolesLoading}
                        />
                    </div>

                    {/* Members permissions table */}
                    {memberResourceAccessControls.length > 0 && (
                        <div>
                            <h3>Members</h3>
                            <LemonTable
                                columns={memberColumns}
                                dataSource={memberResourceAccessControls}
                                loading={rolesLoading}
                            />
                        </div>
                    )}

                    {/* Roles permissions table */}
                    {roleResourceAccessControls.length > 0 && (
                        <div>
                            <h3>Roles</h3>
                            <LemonTable
                                columns={roleColumns}
                                dataSource={roleResourceAccessControls}
                                loading={rolesLoading}
                            />
                        </div>
                    )}
                </div>
            </PayGateMini>
        </div>
    )
}
