import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode, useContext, useEffect, useState } from 'react'

import { IconArrowLeft, IconHome, IconInfo, IconOpenSidebar, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonDropdown,
    LemonLabel,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    LemonTagType,
    Link,
    ProfilePicture,
    Tooltip,
} from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { getAccessControlTooltip } from 'lib/utils/accessControlUtils'
import { fullName, toSentenceCase } from 'lib/utils/strings'
import { SettingsChromeContext } from 'scenes/settings/Settings'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { APIScopeObject, AccessControlLevel, SidePanelTab } from '~/types'

import { AccessLevelEnumApi } from 'products/access_control/frontend/generated/api.schemas'

import { roleAccessControlLogic } from '../roleAccessControlLogic'
import { accessControlsLogic } from './accessControlsLogic'
import { ADD_RULE_RESOURCES, addObjectOverrideModalLogic } from './addObjectOverrideModalLogic'
import { addPropertyRestrictionModalLogic } from './addPropertyRestrictionModalLogic'
import { groupedAccessControlRuleModalLogic } from './groupedAccessControlRuleModalLogic'
import { MemberObjectOverride, MemberPropertyRestriction, memberAccessDetailLogic } from './memberAccessDetailLogic'
import { ScopeIcon } from './ScopeIcon'
import { AccessControlMemberEntry } from './types'

export function MemberAccessControlDetail({ projectId }: { projectId: string }): JSX.Element {
    const { selectedMember, membersDataLoading } = useValues(accessControlsLogic({ projectId }))
    const { closeMemberDetail } = useActions(accessControlsLogic({ projectId }))
    const { setChromeHidden } = useContext(SettingsChromeContext)

    // This detail is a full page — hide the scene title + section heading above it so it reads as its own page.
    useEffect(() => {
        setChromeHidden(true)
        return () => setChromeHidden(false)
    }, [setChromeHidden])

    return (
        <div className="space-y-6">
            <LemonButton icon={<IconArrowLeft />} size="small" onClick={closeMemberDetail} className="-ml-2 w-fit">
                Access control · Members
            </LemonButton>

            {!selectedMember ? (
                membersDataLoading ? (
                    <LemonSkeleton className="h-24 w-full" />
                ) : (
                    <div className="text-secondary">Member not found.</div>
                )
            ) : (
                <MemberAccessControlDetailContent projectId={projectId} member={selectedMember} />
            )}
        </div>
    )
}

function MemberAccessControlDetailContent({
    projectId,
    member,
}: {
    projectId: string
    member: AccessControlMemberEntry
}): JSX.Element {
    // Remount the editable form whenever the member's saved access changes (e.g. after a save reloads the data),
    // so the form state re-initialises from the fresh effective levels instead of holding stale defaults.
    const formKey = `${member.organization_membership_id}:${member.project.effective_access_level}:${Object.entries(
        member.resources
    )
        .map(([k, v]) => `${k}=${v.effective_access_level}`)
        .join(',')}`

    return (
        <>
            <MemberHeader member={member} />

            <ProjectAccessSection key={`project-${formKey}`} projectId={projectId} entry={member} />

            <MemberAccessFields key={formKey} projectId={projectId} entry={member} />

            <ObjectOverridesSection projectId={projectId} membershipId={member.organization_membership_id} />

            <RestrictedPropertiesSection projectId={projectId} membershipId={member.organization_membership_id} />
        </>
    )
}

function MemberHeader({ member }: { member: AccessControlMemberEntry }): JSX.Element {
    return (
        <div className="flex items-center gap-3">
            <ProfilePicture user={member.user} size="xl" />
            <div className="min-w-0">
                <div className="font-medium text-sm truncate">
                    {member.user.first_name ? fullName(member.user) : member.user.email}
                </div>
                {member.user.first_name && <div className="text-secondary text-sm truncate">{member.user.email}</div>}
                <div className="mt-1">
                    <MemberRoles userUuid={member.user.uuid} />
                </div>
            </div>
        </div>
    )
}

function ProjectAccessSection({
    projectId,
    entry,
}: {
    projectId: string
    entry: AccessControlMemberEntry
}): JSX.Element {
    const { formProjectLevel, projectDisabledReason, projectInheritedReasonTooltip, projectLevelOptions } = useValues(
        groupedAccessControlRuleModalLogic({ entry, scopeType: 'member', projectId })
    )
    const { setProjectLevel, save } = useActions(
        groupedAccessControlRuleModalLogic({ entry, scopeType: 'member', projectId })
    )
    const { currentTeam } = useValues(teamLogic)

    const onProjectChange = (level: AccessControlLevel | null): void => {
        setProjectLevel(level)
        save()
    }

    return (
        <div className="p-3 bg-surface-primary rounded border border-border flex flex-row justify-between items-center gap-4">
            <div className="font-medium flex items-center gap-2">
                <span className="text-muted-alt flex items-center">
                    <IconHome />
                </span>
                Project access{currentTeam?.name ? ` · ${currentTeam.name}` : ''}
            </div>
            <LemonSelect
                dropdownPlacement="bottom-end"
                value={formProjectLevel}
                disabledReason={projectDisabledReason}
                tooltip={projectInheritedReasonTooltip}
                size="small"
                className="w-36"
                onChange={onProjectChange}
                options={projectLevelOptions}
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
            data-attr="member-access-roles"
        />
    )
}

function Section({
    title,
    description,
    children,
    action,
}: {
    title: string
    description?: string
    children: ReactNode
    action?: ReactNode
}): JSX.Element {
    return (
        <div className="space-y-2">
            <div className="flex items-start justify-between gap-2">
                <div>
                    <h3 className="mb-0">{title}</h3>
                    {description && <p className="text-secondary text-sm mb-0">{description}</p>}
                </div>
                {action}
            </div>
            {children}
        </div>
    )
}

/** A link to open the object, for resource types whose page is addressable by the stored resource_id (a pk). */
function objectUrl(resource: string, resourceId: string): string | null {
    switch (resource) {
        case 'dashboard':
            return urls.dashboard(resourceId)
        case 'feature_flag':
            return urls.featureFlag(resourceId)
        case 'experiment':
            return urls.experiment(resourceId)
        case 'survey':
            return urls.survey(resourceId)
        case 'action':
            return urls.action(resourceId)
        default:
            // insight / notebook / warehouse pages need a short_id we don't have here — show as plain text
            return null
    }
}

function MemberAccessFields({ projectId, entry }: { projectId: string; entry: AccessControlMemberEntry }): JSX.Element {
    const {
        formResourceLevels,
        featuresDisabledReason,
        isResourceLevelShowingInherited,
        resourceInheritedReasonTooltip,
        resourceLevelOptions,
        showResourceAddOverrideButton,
    } = useValues(groupedAccessControlRuleModalLogic({ entry, scopeType: 'member', projectId }))
    const { setResourceLevel, save } = useActions(
        groupedAccessControlRuleModalLogic({ entry, scopeType: 'member', projectId })
    )

    const { resourceKeys } = useValues(accessControlsLogic({ projectId }))

    const [showAllTools, setShowAllTools] = useState(false)

    // A resource with a set level is an "override"; the rest fall back to the project default (shown as "Add override").
    // Show only the overridden tools; if there are none, show the first 3. Collapse the rest behind a toggle.
    const hasOverride = (key: APIScopeObject): boolean => !showResourceAddOverrideButton(key)
    const overriddenResources = resourceKeys.filter((r) => hasOverride(r.key))
    const baseVisibleKeys = new Set(
        (overriddenResources.length > 0 ? overriddenResources : resourceKeys.slice(0, 3)).map((r) => r.key)
    )
    const collapsedCount = resourceKeys.length - baseVisibleKeys.size
    const canCollapse = collapsedCount > 3
    const visibleResources =
        showAllTools || !canCollapse ? resourceKeys : resourceKeys.filter((r) => baseVisibleKeys.has(r.key))

    // Persist immediately on every change — no explicit save button
    const onResourceChange = (resource: APIScopeObject, level: AccessControlLevel | null): void => {
        setResourceLevel(resource, level)
        save()
    }

    return (
        <>
            <Section title="Tools" description="The access this member has to each tool.">
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
                            render: (_, resource: { key: APIScopeObject; label: string }) => (
                                <div className="flex justify-end py-1.5">
                                    {showResourceAddOverrideButton(resource.key) ? (
                                        <LemonDropdown
                                            placement="bottom-end"
                                            overlay={
                                                <div className="flex flex-col">
                                                    {resourceLevelOptions(resource.key, resource.label).map(
                                                        (option) => (
                                                            <LemonButton
                                                                key={option.value}
                                                                size="small"
                                                                className="w-32"
                                                                fullWidth
                                                                disabledReason={option.disabledReason}
                                                                onClick={() =>
                                                                    onResourceChange(resource.key, option.value)
                                                                }
                                                            >
                                                                {option.label}
                                                            </LemonButton>
                                                        )
                                                    )}
                                                </div>
                                            }
                                        >
                                            <LemonButton
                                                size="small"
                                                type="tertiary"
                                                icon={<IconPlus />}
                                                sideIcon={null}
                                                disabledReason={featuresDisabledReason}
                                                className="whitespace-nowrap"
                                            >
                                                Add override
                                            </LemonButton>
                                        </LemonDropdown>
                                    ) : (
                                        <LemonSelect
                                            className="w-32"
                                            size="small"
                                            value={formResourceLevels[resource.key]}
                                            disabledReason={featuresDisabledReason}
                                            tooltip={resourceInheritedReasonTooltip(resource.key)}
                                            renderButtonContent={(leaf) => {
                                                const level = formResourceLevels[resource.key]
                                                if (isResourceLevelShowingInherited(resource.key) && level) {
                                                    return toSentenceCase(level)
                                                }
                                                return leaf?.label ?? ''
                                            }}
                                            onChange={(value) => onResourceChange(resource.key, value)}
                                            options={resourceLevelOptions(resource.key, resource.label)}
                                        />
                                    )}
                                </div>
                            ),
                        },
                    ]}
                />
                {canCollapse && (
                    <Link className="text-sm" onClick={() => setShowAllTools(!showAllTools)}>
                        {showAllTools ? 'Show fewer' : `Show ${collapsedCount} more tools with no overrides`}
                    </Link>
                )}
            </Section>
        </>
    )
}

const ACCESS_TAGS: Record<string, { label: string; type: LemonTagType }> = {
    none: { label: 'No access', type: 'danger' },
    viewer: { label: 'Viewer', type: 'primary' },
    editor: { label: 'Editor', type: 'success' },
    manager: { label: 'Manager', type: 'completion' },
    read: { label: 'Read only', type: 'primary' },
    read_write: { label: 'Read & write', type: 'success' },
}

function AccessLevelTag({ level }: { level: string }): JSX.Element {
    const tag = ACCESS_TAGS[level] ?? { label: toSentenceCase(level), type: 'default' as LemonTagType }
    return <LemonTag type={tag.type}>{tag.label}</LemonTag>
}

function sourceLabel(row: { source: string; role_name: string | null }): string {
    if (row.source === 'member') {
        return 'Member override'
    }
    if (row.source === 'role') {
        return row.role_name ? `From role: ${row.role_name}` : 'From role'
    }
    return 'Default'
}

function ObjectOverridesSection({ projectId, membershipId }: { projectId: string; membershipId: string }): JSX.Element {
    const { objects, objectsLoading } = useValues(memberAccessDetailLogic({ projectId, membershipId }))
    const { openModal, deleteObjectOverride } = useActions(addObjectOverrideModalLogic({ projectId, membershipId }))

    return (
        <Section
            title="Object overrides"
            description="Individual dashboards, insights, notebooks, warehouse tables & views where this member's access differs from the resource-level access above."
        >
            <AddObjectOverrideModal projectId={projectId} membershipId={membershipId} />
            <LemonTable
                loading={objectsLoading}
                columns={[
                    {
                        title: 'Object',
                        key: 'object',
                        render: (_, o: MemberObjectOverride) => {
                            const href = objectUrl(o.resource, o.resource_id)
                            const label = href ? <Link to={href}>{o.name}</Link> : o.name
                            return (
                                <div className="flex items-center gap-2">
                                    <span className="text-muted-alt flex items-center">
                                        <ScopeIcon scope={o.resource as APIScopeObject} />
                                    </span>
                                    <span className="font-medium">{label}</span>
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Type',
                        key: 'type',
                        render: (_, o: MemberObjectOverride) => (
                            <span className="text-secondary">{toSentenceCase(o.resource.replace(/_/g, ' '))}</span>
                        ),
                    },
                    {
                        title: 'Source',
                        key: 'source',
                        render: (_, o: MemberObjectOverride) => (
                            <span className="text-secondary text-xs">{sourceLabel(o)}</span>
                        ),
                    },
                    {
                        title: 'Access',
                        key: 'access',
                        render: (_, o: MemberObjectOverride) => <AccessLevelTag level={o.access_level} />,
                    },
                    {
                        title: '',
                        key: 'actions',
                        width: 0,
                        render: (_, o: MemberObjectOverride) => {
                            const href = objectUrl(o.resource, o.resource_id)
                            const canDelete = o.source === 'member'
                            if (!href && !canDelete) {
                                return null
                            }
                            return (
                                <More
                                    overlay={
                                        <>
                                            {href && (
                                                <LemonButton
                                                    fullWidth
                                                    icon={<IconOpenSidebar />}
                                                    // Deep-link the object's access-control side panel via the
                                                    // `#panel=` hash so it opens on the destination page.
                                                    onClick={() =>
                                                        router.actions.push(href, undefined, {
                                                            panel: SidePanelTab.AccessControl,
                                                        })
                                                    }
                                                >
                                                    Manage access
                                                </LemonButton>
                                            )}
                                            {canDelete && (
                                                <LemonButton
                                                    fullWidth
                                                    status="danger"
                                                    icon={<IconTrash />}
                                                    onClick={() => deleteObjectOverride(o.resource, o.resource_id)}
                                                >
                                                    Remove rule
                                                </LemonButton>
                                            )}
                                        </>
                                    }
                                />
                            )
                        },
                    },
                ]}
                dataSource={objects}
                pagination={{ pageSize: 20, hideOnSinglePage: true }}
                emptyState="No object-level overrides for this member."
            />
            <div>
                <LemonButton type="secondary" size="small" icon={<IconPlus />} onClick={openModal}>
                    Add rule
                </LemonButton>
            </div>
        </Section>
    )
}

function AddObjectOverrideModal({ projectId, membershipId }: { projectId: string; membershipId: string }): JSX.Element {
    const logic = addObjectOverrideModalLogic({ projectId, membershipId })
    const { isOpen, resource, objectId, level, objectOptions, objectOptionsLoading } = useValues(logic)
    const { closeModal, setResource, setSearch, setObjectId, setLevel, submitRule } = useActions(logic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            title="Add access rule"
            description="Grant or restrict this member's access to a specific object. This creates a member override."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={!objectId ? 'Select an object' : undefined}
                        onClick={submitRule}
                    >
                        Add rule
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-3 min-w-[24rem]">
                <div>
                    <LemonLabel>Type</LemonLabel>
                    <LemonSelect
                        value={resource}
                        onChange={setResource}
                        options={ADD_RULE_RESOURCES.map((r) => ({ value: r.value, label: r.label }))}
                        fullWidth
                    />
                </div>
                <div>
                    <LemonLabel>Object</LemonLabel>
                    <LemonInputSelect
                        mode="single"
                        value={objectId ? [objectId] : []}
                        onChange={(values) => setObjectId(values[0] ?? null)}
                        onInputChange={setSearch}
                        loading={objectOptionsLoading}
                        options={objectOptions.map((o) => ({ key: o.id, label: o.name }))}
                        placeholder="Search by name…"
                    />
                </div>
                <div>
                    <LemonLabel>Access</LemonLabel>
                    <LemonSelect
                        value={level}
                        onChange={setLevel}
                        options={[
                            { value: AccessControlLevel.None, label: 'No access' },
                            { value: AccessControlLevel.Viewer, label: 'Viewer' },
                            { value: AccessControlLevel.Editor, label: 'Editor' },
                            { value: AccessControlLevel.Manager, label: 'Manager' },
                        ]}
                        fullWidth
                    />
                </div>
            </div>
        </LemonModal>
    )
}

function RestrictedPropertiesSection({
    projectId,
    membershipId,
}: {
    projectId: string
    membershipId: string
}): JSX.Element {
    const { properties, propertiesLoading } = useValues(memberAccessDetailLogic({ projectId, membershipId }))
    const { openModal } = useActions(addPropertyRestrictionModalLogic({ projectId, membershipId }))

    return (
        <Section
            title="Restricted properties"
            description="Properties this member cannot read & write freely. Default for every property is read & write."
        >
            <AddPropertyRestrictionModal projectId={projectId} membershipId={membershipId} />
            <LemonTable
                loading={propertiesLoading}
                columns={[
                    {
                        title: 'Property',
                        key: 'property',
                        render: (_, p: MemberPropertyRestriction) => <span className="font-medium">{p.property}</span>,
                    },
                    {
                        title: 'Scope',
                        key: 'scope',
                        render: (_, p: MemberPropertyRestriction) => (
                            <span className="text-secondary">
                                {p.property_type === 'person' ? 'Person property' : 'Event property'}
                            </span>
                        ),
                    },
                    {
                        title: 'Source',
                        key: 'source',
                        render: (_, p: MemberPropertyRestriction) => (
                            <span className="text-secondary text-xs">{sourceLabel(p)}</span>
                        ),
                    },
                    {
                        title: 'Access',
                        key: 'access',
                        render: (_, p: MemberPropertyRestriction) => <AccessLevelTag level={p.access_level} />,
                    },
                ]}
                dataSource={properties}
                pagination={{ pageSize: 20, hideOnSinglePage: true }}
                emptyState="No restricted properties for this member."
            />
            <div>
                <LemonButton type="secondary" size="small" icon={<IconPlus />} onClick={openModal}>
                    Add rule
                </LemonButton>
            </div>
        </Section>
    )
}

function AddPropertyRestrictionModal({
    projectId,
    membershipId,
}: {
    projectId: string
    membershipId: string
}): JSX.Element {
    const logic = addPropertyRestrictionModalLogic({ projectId, membershipId })
    const { isOpen, propertyType, propertyId, level, propertyOptions, propertyOptionsLoading } = useValues(logic)
    const { closeModal, setPropertyType, setSearch, setPropertyId, setLevel, submitRule } = useActions(logic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            title="Restrict a property"
            description="Limit this member's access to a specific property. This creates a member override."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={!propertyId ? 'Select a property' : undefined}
                        onClick={submitRule}
                    >
                        Add rule
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-3 min-w-[24rem]">
                <div>
                    <LemonLabel>Scope</LemonLabel>
                    <LemonSelect
                        value={propertyType}
                        onChange={setPropertyType}
                        options={[
                            { value: 'person', label: 'Person property' },
                            { value: 'event', label: 'Event property' },
                        ]}
                        fullWidth
                    />
                </div>
                <div>
                    <LemonLabel>Property</LemonLabel>
                    <LemonInputSelect
                        mode="single"
                        value={propertyId ? [propertyId] : []}
                        onChange={(values) => setPropertyId(values[0] ?? null)}
                        onInputChange={setSearch}
                        loading={propertyOptionsLoading}
                        options={propertyOptions.map((o) => ({ key: o.id, label: o.name }))}
                        placeholder="Search by name…"
                    />
                </div>
                <div>
                    <LemonLabel>Access</LemonLabel>
                    <LemonSelect
                        value={level}
                        onChange={setLevel}
                        options={[
                            { value: AccessLevelEnumApi.Read, label: 'Read only' },
                            { value: AccessLevelEnumApi.None, label: 'Hidden' },
                        ]}
                        fullWidth
                    />
                </div>
            </div>
        </LemonModal>
    )
}
