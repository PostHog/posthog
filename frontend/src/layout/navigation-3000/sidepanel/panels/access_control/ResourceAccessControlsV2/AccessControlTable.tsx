import { capitalizeFirstLetter } from 'kea-forms'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, LemonTag, ProfilePicture } from '@posthog/lemon-ui'

import { pluralizeResource } from 'lib/utils/accessControlUtils'

import { APIScopeObject } from '~/types'

import { getEntryId } from './accessControlsLogic'
import {
    AccessControlMemberEntry,
    AccessControlRoleEntry,
    AccessControlSettingsEntry,
    AccessControlsTab,
} from './types'

function isRoleEntry(entry: AccessControlSettingsEntry): entry is AccessControlRoleEntry {
    return 'role_id' in entry
}

function isMemberEntry(entry: AccessControlSettingsEntry): entry is AccessControlMemberEntry {
    return 'organization_membership_id' in entry
}

function getScopeColumnsForTab(activeTab: AccessControlsTab): LemonTableColumns<AccessControlSettingsEntry> {
    switch (activeTab) {
        case 'roles':
            return [
                {
                    title: 'Role',
                    key: 'role',
                    render: function RenderRole(_: any, entry: AccessControlSettingsEntry) {
                        return <span>{isRoleEntry(entry) ? entry.role_name : ''}</span>
                    },
                },
            ]
        case 'members':
            return [
                {
                    title: 'Member',
                    key: 'member',
                    render: function RenderMember(_: any, entry: AccessControlSettingsEntry) {
                        if (!isMemberEntry(entry)) {
                            return null
                        }
                        return (
                            <div className="flex items-center gap-3">
                                <ProfilePicture
                                    user={{
                                        first_name: entry.user.first_name,
                                        email: entry.user.email,
                                    }}
                                />
                                <div className="overflow-hidden">
                                    <p className="font-medium mb-0 truncate">
                                        {entry.user.first_name || entry.user.email}
                                    </p>
                                    <p className="text-secondary font-light mb-0 truncate text-xs">
                                        {entry.user.email}
                                    </p>
                                </div>
                            </div>
                        )
                    },
                },
            ]
        case 'defaults':
            return []
    }
}

export interface AccessControlTableProps {
    activeTab: AccessControlsTab
    entries: AccessControlSettingsEntry[]
    loading: boolean
    canEditAny: boolean
    onEdit: (entry: AccessControlSettingsEntry) => void
}

export function AccessControlTable(props: AccessControlTableProps): JSX.Element {
    const columns = getColumns(props.activeTab, props.canEditAny, props.onEdit)

    return (
        <LemonTable
            columns={columns}
            dataSource={props.entries}
            loading={props.loading}
            rowKey={(entry) => getEntryId(entry)}
            emptyState="No access control rules match these filters"
            pagination={{ pageSize: 50, hideOnSinglePage: true }}
            onRow={(entry) => ({
                className: props.canEditAny ? 'group cursor-pointer hover:bg-surface-secondary' : undefined,
                onClick: (event) => {
                    if (!props.canEditAny) {
                        return
                    }
                    if ((event.target as HTMLElement).closest('button, a, [role="button"]')) {
                        return
                    }
                    props.onEdit(entry)
                },
            })}
        />
    )
}

function AccessSummary({ entry }: { entry: AccessControlSettingsEntry }): JSX.Element {
    const tags: { resource: string; level: string }[] = []

    // Showing project effective access level
    if (entry.project.effective_access_level) {
        tags.push({ resource: 'project', level: entry.project.effective_access_level })
    }

    for (const [resource, resourceEntry] of Object.entries(entry.resources)) {
        if (resourceEntry.effective_access_level) {
            tags.push({ resource, level: resourceEntry.effective_access_level })
        }
    }

    if (tags.length === 0) {
        return <span className="text-muted">No access configured</span>
    }

    const projectTag = tags.find((t) => t.resource === 'project')
    const resourceTags = tags.filter((t) => t.resource !== 'project')
    const MAX_VISIBLE_RESOURCE_TAGS = 3
    const visibleResourceTags = resourceTags.slice(0, MAX_VISIBLE_RESOURCE_TAGS)
    const hiddenCount = resourceTags.length - MAX_VISIBLE_RESOURCE_TAGS

    return (
        <div className="flex gap-2 flex-wrap items-center">
            {projectTag && (
                <LemonTag key="project" type="default" className="font-semibold border-border-bold-3000">
                    Project: {capitalizeFirstLetter(projectTag.level)}
                </LemonTag>
            )}
            {visibleResourceTags.map(({ resource, level }) => (
                <LemonTag key={resource} type="muted" className="group-hover:bg-transparent">
                    {capitalizeFirstLetter(pluralizeResource(resource as APIScopeObject))}:{' '}
                    {capitalizeFirstLetter(level)}
                </LemonTag>
            ))}
            {hiddenCount > 0 && <span className="text-warning text-xs">+{hiddenCount} more</span>}
        </div>
    )
}

function getColumns(
    activeTab: AccessControlsTab,
    canEditAny: boolean,
    onEdit: (entry: AccessControlSettingsEntry) => void
): LemonTableColumns<AccessControlSettingsEntry> {
    const scopeColumns = getScopeColumnsForTab(activeTab)

    return [
        ...scopeColumns,
        {
            title: 'Access',
            key: 'resource',
            render: function RenderResource(_: any, entry: AccessControlSettingsEntry) {
                return <AccessSummary entry={entry} />
            },
        },
        {
            title: '',
            key: 'actions',
            width: 0,
            align: 'right' as const,
            render: function RenderActions(_: any, entry: AccessControlSettingsEntry) {
                return (
                    <LemonButton
                        size="small"
                        fullWidth
                        icon={<IconPencil />}
                        disabledReason={!canEditAny ? 'You cannot edit this' : undefined}
                        onClick={() => onEdit(entry)}
                    >
                        Edit
                    </LemonButton>
                )
            },
        },
    ]
}
