import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonSelect, LemonSelectOptionLeaf } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ProfileBubbles, ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { AccessLevelEnumApi } from 'products/access_control/frontend/generated/api.schemas'

import { propertyAccessControlLogic, PropertyAccessControlLogicProps } from './propertyAccessControlLogic'

const ACCESS_LEVEL_OPTIONS: LemonSelectOptionLeaf<AccessLevelEnumApi>[] = [
    { value: 'read_write', label: 'Read & write' },
    { value: 'read', label: 'Read only' },
    { value: 'none', label: 'No access' },
]

const OVERRIDE_OPTIONS: LemonSelectOptionLeaf<AccessLevelEnumApi | null>[] = [
    ...ACCESS_LEVEL_OPTIONS,
    { value: null, label: 'Remove override' },
]

interface PropertyAccessControlProps {
    propertyDefinitionId: string
    teamId: number
}

export function PropertyAccessControl({ propertyDefinitionId, teamId }: PropertyAccessControlProps): JSX.Element {
    const logicProps: PropertyAccessControlLogicProps = { propertyDefinitionId, teamId }
    const { remoteStateLoading, defaultLevel, memberOverrides, roleOverrides, allMembers, allRoles, activeTab } =
        useValues(propertyAccessControlLogic(logicProps))
    const { setLocalDefaultLevel, setLocalMemberOverride, setLocalRoleOverride, setActiveTab } = useActions(
        propertyAccessControlLogic(logicProps)
    )

    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (remoteStateLoading) {
        return <Spinner />
    }

    return (
        <div className="space-y-4">
            <LemonField.Pure
                label="Default access level"
                help="This is the base access level for all users when no member or role override applies."
            >
                <LemonSelect
                    value={defaultLevel}
                    onChange={(value) => setLocalDefaultLevel(value)}
                    options={ACCESS_LEVEL_OPTIONS}
                    size="small"
                    className="max-w-48"
                    disabledReason={restrictedReason}
                />
            </LemonField.Pure>

            <LemonTabs
                activeKey={activeTab}
                onChange={setActiveTab}
                tabs={[
                    {
                        key: 'members',
                        label: 'Members',
                        content: (
                            <MembersTab
                                members={allMembers}
                                overrides={memberOverrides}
                                onSetOverride={setLocalMemberOverride}
                                restrictedReason={restrictedReason}
                            />
                        ),
                    },
                    {
                        key: 'roles',
                        label: 'Roles',
                        content: (
                            <RolesTab
                                roles={allRoles}
                                overrides={roleOverrides}
                                onSetOverride={setLocalRoleOverride}
                                restrictedReason={restrictedReason}
                            />
                        ),
                    },
                ]}
            />
        </div>
    )
}

interface MemberInfo {
    id: string
    first_name: string
    last_name: string
    email: string
}

interface RoleInfo {
    id: string
    name: string
    members: MemberInfo[]
}

function OverrideCell({
    currentLevel,
    onChange,
    restrictedReason,
}: {
    currentLevel: AccessLevelEnumApi | null | undefined
    onChange: (level: AccessLevelEnumApi | null) => void
    restrictedReason: string | null
}): JSX.Element {
    const hasOverride = currentLevel != null

    if (hasOverride) {
        return (
            <LemonSelect
                value={currentLevel}
                onChange={onChange}
                options={OVERRIDE_OPTIONS}
                size="small"
                className="w-40"
                disabledReason={restrictedReason}
            />
        )
    }

    return (
        <LemonDropdown
            placement="bottom-end"
            overlay={
                <div className="flex flex-col">
                    {ACCESS_LEVEL_OPTIONS.map((option) => (
                        <LemonButton
                            key={option.value}
                            size="small"
                            className="w-40"
                            fullWidth
                            onClick={() => onChange(option.value)}
                        >
                            {option.label}
                        </LemonButton>
                    ))}
                </div>
            }
        >
            <LemonButton
                size="small"
                type="tertiary"
                icon={<IconPlus />}
                sideIcon={null}
                className="w-40"
                disabledReason={restrictedReason}
            >
                Add override
            </LemonButton>
        </LemonDropdown>
    )
}

function MembersTab({
    members,
    overrides,
    onSetOverride,
    restrictedReason,
}: {
    members: MemberInfo[]
    overrides: Record<string, AccessLevelEnumApi | null>
    onSetOverride: (memberId: string, level: AccessLevelEnumApi | null) => void
    restrictedReason: string | null
}): JSX.Element {
    const columns: LemonTableColumn<MemberInfo, keyof MemberInfo | undefined>[] = [
        {
            title: 'Member',
            key: 'name',
            render: (_, member) => (
                <div className="flex items-center gap-2">
                    <ProfilePicture user={{ first_name: member.first_name, email: member.email }} size="md" />
                    <div>
                        <div className="font-semibold">
                            {member.first_name} {member.last_name}
                        </div>
                        <div className="text-muted text-xs">{member.email}</div>
                    </div>
                </div>
            ),
        },
        {
            title: 'Access level',
            key: 'access',
            width: 200,
            render: (_, member) => (
                <OverrideCell
                    currentLevel={overrides[member.id]}
                    onChange={(level) => onSetOverride(member.id, level)}
                    restrictedReason={restrictedReason}
                />
            ),
        },
    ]

    return <LemonTable dataSource={members} columns={columns} rowKey="id" size="small" emptyState="No members found" />
}

function RolesTab({
    roles,
    overrides,
    onSetOverride,
    restrictedReason,
}: {
    roles: RoleInfo[]
    overrides: Record<string, AccessLevelEnumApi | null>
    onSetOverride: (roleId: string, level: AccessLevelEnumApi | null) => void
    restrictedReason: string | null
}): JSX.Element {
    const columns: LemonTableColumn<RoleInfo, keyof RoleInfo | undefined>[] = [
        {
            title: 'Role',
            key: 'name',
            render: (_, role) => <span className="font-semibold">{role.name}</span>,
        },
        {
            title: 'Members',
            key: 'members',
            render: (_, role) => (
                <ProfileBubbles
                    people={role.members.map((m) => ({
                        email: m.email,
                        name: `${m.first_name} ${m.last_name}`,
                        title: `${m.first_name} ${m.last_name} <${m.email}>`,
                    }))}
                    limit={4}
                />
            ),
        },
        {
            title: 'Access level',
            key: 'access',
            width: 200,
            render: (_, role) => (
                <OverrideCell
                    currentLevel={overrides[role.id]}
                    onChange={(level) => onSetOverride(role.id, level)}
                    restrictedReason={restrictedReason}
                />
            ),
        },
    ]

    return <LemonTable dataSource={roles} columns={columns} rowKey="id" size="small" emptyState="No roles found" />
}
