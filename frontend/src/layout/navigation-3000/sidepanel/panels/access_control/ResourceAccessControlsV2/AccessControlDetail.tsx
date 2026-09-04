import { useActions, useValues } from 'kea'

import { IconGear, IconHome, IconInfo, IconPeople, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, Link, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { getAccessControlTooltip } from 'lib/utils/accessControlUtils'
import { fullName } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { APIScopeObject, AccessControlLevel } from '~/types'

import { AccessLevelSelect } from '../AccessLevelSelect'
import { roleAccessControlLogic } from '../roleAccessControlLogic'
import { accessControlsLogic } from './accessControlsLogic'
import { AccessDetailSubjectScope } from './accessDetailLogic'
import { AccessDetailSection } from './AccessDetailSection'
import { getEntryId, inheritedFor, isMemberEntry, subjectDisabledReason } from './helpers'
import { ObjectAccessRules } from './ObjectAccessRules'
import { PropertyAccessRules } from './PropertyAccessRules'
import { ScopeIcon } from './ScopeIcon'
import { AccessControlMemberEntry, AccessControlRoleEntry, AccessControlSettingsEntry } from './types'

export function AccessControlDetailContent({
    projectId,
    scopeType,
    entry,
}: {
    projectId: string
    scopeType: AccessDetailSubjectScope
    entry: AccessControlSettingsEntry
}): JSX.Element {
    const subjectId = getEntryId(entry)
    const subjectNoun = scopeType === 'role' ? 'role' : 'member'
    const { canEdit } = useValues(accessControlsLogic({ projectId }))
    const { user } = useValues(userLogic)

    // The same gate as the project select and tools above, so the whole page greys out together
    // (permissions, self-edits, org admins who always have full access)
    const cannotEditReason = subjectDisabledReason(entry, canEdit, user?.uuid)

    return (
        <>
            {isMemberEntry(entry) ? <MemberHeader member={entry} /> : <RoleHeader role={entry} />}

            <ProjectAccessSection projectId={projectId} scopeType={scopeType} entry={entry} />

            <ToolsSection projectId={projectId} scopeType={scopeType} entry={entry} subjectNoun={subjectNoun} />

            <ObjectAccessRules
                projectId={projectId}
                scopeType={scopeType}
                subjectId={subjectId}
                subjectNoun={subjectNoun}
                canEdit={!cannotEditReason}
                cannotEditReason={cannotEditReason}
            />

            <PropertyAccessRules
                projectId={projectId}
                scopeType={scopeType}
                subjectId={subjectId}
                subjectNoun={subjectNoun}
                canEdit={!cannotEditReason}
                cannotEditReason={cannotEditReason}
            />
        </>
    )
}

function MemberHeader({ member }: { member: AccessControlMemberEntry }): JSX.Element {
    return (
        // Top aligned so the reserved height of the roles line below doesn't drag the avatar down,
        // nudged to sit optically level with the name and email
        <div className="flex items-start gap-3">
            <ProfilePicture user={member.user} size="xl" className="mt-2" />
            <div className="min-w-0">
                <div className="font-medium text-sm truncate">
                    {member.user.first_name ? fullName(member.user) : member.user.email}
                </div>
                {member.user.first_name && <div className="text-secondary text-sm truncate">{member.user.email}</div>}
                {/* Reserves the height of the LemonInput the tags turn into, with the tags at the
                    top of it, so clicking Edit roles moves nothing above or below. A couple of
                    pixels over --lemon-input-height, which the input's borders push past */}
                <div className="mt-1 min-h-[calc(2.125rem_+_5px)] flex items-start">
                    <MemberRoles userUuid={member.user.uuid} />
                </div>
            </div>
        </div>
    )
}

function RoleHeader({ role }: { role: AccessControlRoleEntry }): JSX.Element {
    const { sortedRoles, canEditRoles } = useValues(roleAccessControlLogic)
    const { deleteRole } = useActions(roleAccessControlLogic)
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    const members = sortedRoles.find((r) => r.id === role.role_id)?.members ?? []

    const confirmDelete = (): void => {
        LemonDialog.open({
            title: `Delete the ${role.role_name} role?`,
            maxWidth: '30rem',
            description: (
                <div className="space-y-2">
                    <p className="mb-0">
                        This removes every access rule the role grants, in this project and in every other project in
                        the organization.
                    </p>
                    {members.length > 0 && (
                        <p className="mb-0">
                            {members.length === 1 ? '1 member loses' : `${members.length} members lose`} the role:{' '}
                            {members
                                .map((m) => (m.user.first_name ? fullName(m.user) : m.user.email))
                                .sort()
                                .join(', ')}
                            .
                        </p>
                    )}
                </div>
            ),
            primaryButton: {
                children: 'Delete role',
                status: 'danger',
                onClick: () => {
                    deleteRole(role.role_id)
                    // The role this panel shows is gone, so don't stay open on "Role not found"
                    closeSidePanel()
                },
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
                <span className="text-muted-alt flex items-center text-lg">
                    <IconPeople />
                </span>
                <div className="font-medium">{role.role_name}</div>
            </div>
            <More
                overlay={
                    <>
                        <LemonButton
                            fullWidth
                            size="small"
                            icon={<IconGear />}
                            to={urls.settings('organization-roles')}
                        >
                            Manage roles
                        </LemonButton>
                        <LemonButton
                            fullWidth
                            size="small"
                            status="danger"
                            icon={<IconTrash />}
                            disabledReason={canEditRoles === false ? 'You cannot edit roles' : undefined}
                            onClick={confirmDelete}
                        >
                            Delete role
                        </LemonButton>
                    </>
                }
            />
        </div>
    )
}

function ProjectAccessSection({
    projectId,
    scopeType,
    entry,
}: {
    projectId: string
    scopeType: AccessDetailSubjectScope
    entry: AccessControlSettingsEntry
}): JSX.Element {
    const { availableProjectLevels, canEdit } = useValues(accessControlsLogic({ projectId }))
    const { updateAccessControlMembers, updateAccessControlRoles } = useActions(accessControlsLogic({ projectId }))
    const { currentTeam } = useValues(teamLogic)
    const { user } = useValues(userLogic)

    const subjectId = getEntryId(entry)

    const onChange = (level: AccessControlLevel | null): void => {
        if (scopeType === 'role') {
            updateAccessControlRoles([{ role: subjectId, level }], 'v2')
        } else {
            updateAccessControlMembers([{ member: subjectId, level }], 'v2')
        }
    }

    return (
        <div className="p-3 bg-surface-primary rounded border border-border flex flex-row justify-between items-center gap-4">
            <div className="font-medium flex items-center gap-2">
                <span className="text-muted-alt flex items-center">
                    <IconHome />
                </span>
                Project access
                {currentTeam?.name ? <span className="font-normal text-tertiary">· {currentTeam.name}</span> : null}
                <Tooltip
                    title={
                        <div className="space-y-1">
                            <div>
                                <b>Admin</b>: change project settings, rename or delete the project, and manage access.
                            </div>
                            <div>
                                <b>Member</b>: open and use the project, with access to each tool set below.
                            </div>
                            <div>
                                <b>No access</b>: the project is hidden entirely.
                            </div>
                        </div>
                    }
                >
                    <IconInfo className="text-base text-muted" />
                </Tooltip>
            </div>
            <AccessLevelSelect
                size="small"
                dropdownPlacement="bottom-end"
                level={entry.project.access_level}
                levels={availableProjectLevels}
                onChange={onChange}
                disabledReason={subjectDisabledReason(entry, canEdit, user?.uuid)}
                inherited={inheritedFor(entry.project, 'this project')}
                // Falls back to a plain "No override" for a subject with nothing above them, which
                // is the project's own default rather than a member or a role
                allowNoOverride
            />
        </div>
    )
}

function MemberRoles({ userUuid }: { userUuid: string }): JSX.Element {
    const { sortedRoles, rolesLoading, canEditRoles } = useValues(roleAccessControlLogic)
    const { addMembersToRole, removeMemberFromRole, createRoleWithMember } = useActions(roleAccessControlLogic)

    // `user_uuid` on role members is write-only in the API — the readable id is `member.user.uuid`.
    const currentRoles = sortedRoles.filter((r) => r.members.some((m) => m.user.uuid === userUuid))
    const currentNames = currentRoles.map((r) => r.name)

    const onChange = (newNames: string[]): void => {
        // ObjectTags lowercases every value before it reaches us (see cleanTag), so match roles case-insensitively.
        const rolesByLowerName = new Map(sortedRoles.map((r) => [r.name.toLowerCase(), r]))
        const currentLower = new Map(currentRoles.map((r) => [r.name.toLowerCase(), r]))
        const nextLower = new Set(newNames.map((n) => n.toLowerCase()))

        for (const lowerName of nextLower) {
            if (currentLower.has(lowerName)) {
                continue
            }
            const role = rolesByLowerName.get(lowerName)
            if (role) {
                addMembersToRole(role, [userUuid])
            } else {
                // Genuinely new role name — create it and assign the member in one step
                createRoleWithMember(lowerName, userUuid)
            }
        }
        for (const [lowerName, role] of currentLower) {
            if (nextLower.has(lowerName)) {
                continue
            }
            const roleMember = role.members.find((m) => m.user.uuid === userUuid)
            if (roleMember) {
                removeMemberFromRole(role, roleMember.id)
            }
        }
    }

    return canEditRoles === false ? (
        <ObjectTags tags={currentNames} staticOnly data-attr="member-access-roles" />
    ) : (
        <ObjectTags
            tags={currentNames}
            onChange={onChange}
            saving={rolesLoading}
            tagsAvailable={sortedRoles.map((r) => r.name).filter((n) => !currentNames.includes(n))}
            addLabel="Add roles"
            editLabel="Edit roles"
            inputPlaceholder="Add role…"
            // Match the role tags themselves, which render at the default medium size
            actionButtonSize="medium"
            data-attr="member-access-roles"
        />
    )
}

function ToolsSection({
    projectId,
    scopeType,
    entry,
    subjectNoun,
}: {
    projectId: string
    scopeType: AccessDetailSubjectScope
    entry: AccessControlSettingsEntry
    subjectNoun: string
}): JSX.Element {
    const { availableResourceLevels, canEdit, showAllTools, toolsCollapse } = useValues(
        accessControlsLogic({ projectId })
    )
    const { updateResourceAccessControls, setShowAllTools } = useActions(accessControlsLogic({ projectId }))
    const { user } = useValues(userLogic)

    const subjectId = getEntryId(entry)
    const { visibleResources, collapsedCount, canCollapse } = toolsCollapse

    // Persist immediately on every change — no explicit save button
    const onResourceChange = (resource: APIScopeObject, level: AccessControlLevel | null): void => {
        updateResourceAccessControls(
            [
                {
                    resource,
                    access_level: level,
                    role: scopeType === 'role' ? subjectId : null,
                    organization_member: scopeType === 'member' ? subjectId : null,
                },
            ],
            scopeType
        )
    }

    return (
        <AccessDetailSection title="Tools" description={`The access this ${subjectNoun} has to each tool.`}>
            <LemonTable
                showHeader={false}
                dataSource={visibleResources}
                rowKey="key"
                columns={[
                    {
                        title: 'Feature',
                        key: 'feature',
                        render: (_, resource: { key: APIScopeObject; label: string }) => {
                            const tooltipText = getAccessControlTooltip(resource.key)
                            return (
                                <div className="flex items-center gap-2">
                                    <span className="text-muted-alt flex items-center">
                                        <ScopeIcon scope={resource.key} />
                                    </span>
                                    <span className="font-medium">{resource.label}</span>
                                    {tooltipText && (
                                        <Tooltip title={tooltipText}>
                                            <IconInfo className="text-xs text-muted" />
                                        </Tooltip>
                                    )}
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Access',
                        key: 'access',
                        align: 'right',
                        render: (_, resource: { key: APIScopeObject; label: string }) => {
                            const res = entry.resources[resource.key]
                            const maximum = res?.maximum
                            const levels = maximum
                                ? availableResourceLevels.slice(0, availableResourceLevels.indexOf(maximum) + 1)
                                : availableResourceLevels
                            return (
                                <div className="flex justify-end py-1.5">
                                    <AccessLevelSelect
                                        size="small"
                                        dropdownPlacement="bottom-end"
                                        level={res?.access_level ?? null}
                                        levels={levels}
                                        minimumLevel={res?.minimum}
                                        onChange={(level) => onResourceChange(resource.key, level)}
                                        disabledReason={subjectDisabledReason(entry, canEdit, user?.uuid)}
                                        inherited={inheritedFor(res, resource.label.toLowerCase())}
                                    />
                                </div>
                            )
                        },
                    },
                ]}
            />
            {canCollapse && (
                <Link className="text-sm" onClick={() => setShowAllTools(!showAllTools)}>
                    {showAllTools ? 'Show fewer' : `Show ${collapsedCount} more tools with no overrides`}
                </Link>
            )}
        </AccessDetailSection>
    )
}
