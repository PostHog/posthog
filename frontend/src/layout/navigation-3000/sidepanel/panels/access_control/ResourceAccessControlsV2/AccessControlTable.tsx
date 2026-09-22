import clsx from 'clsx'
import { capitalizeFirstLetter } from 'kea-forms'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, LemonTag, ProfilePicture } from '@posthog/lemon-ui'

import { pluralizeResource } from 'lib/utils/accessControlUtils'
import { fullName } from 'lib/utils/strings'

import { APIScopeObject } from '~/types'

import { getAccessSummaryTags, getEntryId, isMemberEntry, isRoleEntry } from './helpers'
import { AccessControlSettingsEntry, AccessControlsTab } from './types'

const MAX_VISIBLE_TAGS = 4

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
                                <ProfilePicture user={entry.user} />
                                <div className="overflow-hidden">
                                    {entry.user.first_name ? (
                                        <>
                                            <p className="font-medium mb-0 truncate">{fullName(entry.user)}</p>
                                            <p className="text-secondary font-light mb-0 truncate text-xs">
                                                {entry.user.email}
                                            </p>
                                        </>
                                    ) : (
                                        <p className="text-secondary mb-0 truncate">{entry.user.email}</p>
                                    )}
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
    visibleResources: Set<APIScopeObject>
    /** The tools selected in the Tool filter. They limit which tags each row shows. */
    filteredResources: Set<APIScopeObject>
    onEdit: (entry: AccessControlSettingsEntry) => void
    /** Entry whose detail is currently open, highlighted in the list */
    selectedEntryId?: string | null
}

export function AccessControlTable(props: AccessControlTableProps): JSX.Element {
    const columns = getColumns(
        props.activeTab,
        props.canEditAny,
        props.visibleResources,
        props.filteredResources,
        props.onEdit
    )

    return (
        <LemonTable
            columns={columns}
            dataSource={props.entries}
            loading={props.loading}
            rowKey={(entry) => getEntryId(entry)}
            emptyState="No access control rules match these filters"
            pagination={{ pageSize: 50, hideOnSinglePage: true }}
            onRow={(entry) => ({
                className: clsx(
                    props.canEditAny && 'cursor-pointer hover:bg-surface-secondary',
                    getEntryId(entry) === props.selectedEntryId && 'bg-primary-highlight'
                ),
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

function AccessSummary({
    entry,
    visibleResources,
    filteredResources,
}: {
    entry: AccessControlSettingsEntry
    visibleResources: Set<APIScopeObject>
    filteredResources: Set<APIScopeObject>
}): JSX.Element {
    const tags = getAccessSummaryTags(entry, visibleResources, filteredResources)

    if (tags.length === 0) {
        return <span className="text-muted">No access configured</span>
    }

    // The project tag comes first and counts towards the limit, so a row keeps the same width
    // whether or not the Tool filter removed it
    const visibleTags = tags.slice(0, MAX_VISIBLE_TAGS)
    const hiddenCount = tags.length - visibleTags.length

    return (
        <div className="flex gap-2 flex-wrap items-center">
            {visibleTags.map(({ resource, level }) => (
                <LemonTag key={resource} type="default">
                    {resource === 'project'
                        ? 'Project'
                        : capitalizeFirstLetter(pluralizeResource(resource as APIScopeObject))}
                    : {capitalizeFirstLetter(level)}
                </LemonTag>
            ))}
            {hiddenCount > 0 && <span className="text-warning text-xs">+{hiddenCount} more</span>}
        </div>
    )
}

function getColumns(
    activeTab: AccessControlsTab,
    canEditAny: boolean,
    visibleResources: Set<APIScopeObject>,
    filteredResources: Set<APIScopeObject>,
    onEdit: (entry: AccessControlSettingsEntry) => void
): LemonTableColumns<AccessControlSettingsEntry> {
    const scopeColumns = getScopeColumnsForTab(activeTab)

    return [
        ...scopeColumns,
        {
            title: 'Access',
            key: 'resource',
            // This column takes the space that the other columns do not use. The other columns
            // then get the width of their content, and this one starts at the same position for
            // each filter.
            width: '100%',
            render: function RenderResource(_: any, entry: AccessControlSettingsEntry) {
                return (
                    <AccessSummary
                        entry={entry}
                        visibleResources={visibleResources}
                        filteredResources={filteredResources}
                    />
                )
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
