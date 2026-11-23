import type { ColumnDef } from '@tanstack/react-table'
import { capitalizeFirstLetter } from 'kea-forms'

import { IconPencil } from '@posthog/icons'
import { Badge, Button, DataTable, Skeleton, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { resourceLabel } from 'lib/utils/accessControlUtils'
import { fullName } from 'lib/utils/strings'

import { APIScopeObject } from '~/types'

import { AccessControlTableProps, MAX_VISIBLE_TAGS } from './AccessControlTable'
import { getAccessSummaryTags, getEntryId, isMemberEntry, isRoleEntry } from './helpers'
import { AccessControlSettingsEntry, AccessControlsTab } from './types'

const ENTRIES_PER_PAGE = 50

function scopeColumnsForTab(activeTab: AccessControlsTab): ColumnDef<AccessControlSettingsEntry>[] {
    switch (activeTab) {
        case 'roles':
            return [
                {
                    id: 'role',
                    header: 'Role',
                    enableSorting: false,
                    cell: ({ row }) => {
                        if (!isRoleEntry(row.original)) {
                            return null
                        }
                        // Access takes all free width, so a wrapping name shrinks this column to one word
                        return (
                            <Tooltip>
                                <TooltipTrigger render={<span className="block max-w-60 truncate font-medium" />}>
                                    {row.original.role_name}
                                </TooltipTrigger>
                                <TooltipContent>{row.original.role_name}</TooltipContent>
                            </Tooltip>
                        )
                    },
                },
            ]
        case 'members':
            return [
                {
                    id: 'member',
                    header: 'Member',
                    enableSorting: false,
                    cell: ({ row }) => {
                        if (!isMemberEntry(row.original)) {
                            return null
                        }
                        const { user } = row.original
                        return (
                            <div className="ph-no-capture flex min-w-0 items-center gap-2">
                                <QuillPersonAvatar name={fullName(user)} email={user.email} />
                                <div className="flex min-w-0 flex-col">
                                    {user.first_name ? (
                                        <>
                                            <Text size="xs" weight="medium" render={<span className="truncate" />}>
                                                {fullName(user)}
                                            </Text>
                                            <Text size="xs" variant="muted" render={<span className="truncate" />}>
                                                {user.email}
                                            </Text>
                                        </>
                                    ) : (
                                        <Text size="xs" variant="muted" render={<span className="truncate" />}>
                                            {user.email}
                                        </Text>
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

function QuillAccessSummary({
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
        return (
            <Text size="xs" variant="muted" render={<span />}>
                No access configured
            </Text>
        )
    }

    // The project tag comes first and counts towards the limit, so a row keeps the same width
    // whether or not the Product filter removed it
    const visibleTags = tags.slice(0, MAX_VISIBLE_TAGS)
    const hiddenCount = tags.length - visibleTags.length

    return (
        <div className="flex flex-wrap items-center gap-2">
            {visibleTags.map(({ resource, level }) => (
                <Badge key={resource}>
                    {`${resource === 'project' ? 'Project' : resourceLabel(resource as APIScopeObject)}: ${capitalizeFirstLetter(level)}`}
                </Badge>
            ))}
            {hiddenCount > 0 && (
                <Text size="xs" render={<span className="text-warning-foreground" />}>
                    {`+${hiddenCount} more`}
                </Text>
            )}
        </div>
    )
}

export function QuillAccessControlTable(props: AccessControlTableProps): JSX.Element {
    const columns: ColumnDef<AccessControlSettingsEntry>[] = [
        ...scopeColumnsForTab(props.activeTab),
        {
            id: 'resource',
            header: 'Access',
            meta: { expand: true },
            enableSorting: false,
            cell: ({ row }) => (
                <QuillAccessSummary
                    entry={row.original}
                    visibleResources={props.visibleResources}
                    filteredResources={props.filteredResources}
                />
            ),
        },
        {
            id: 'actions',
            header: '',
            meta: { align: 'right' },
            enableSorting: false,
            cell: ({ row }) => (
                <Button
                    disabledReason={!props.canEditAny ? (props.cannotEditReason ?? 'You cannot edit this') : undefined}
                    onClick={() => props.onEdit(row.original)}
                >
                    <IconPencil />
                    Edit
                </Button>
            ),
        },
    ]

    if (props.loading && props.entries.length === 0) {
        return <Skeleton className="h-48 w-full" />
    }

    return (
        <DataTable
            columns={columns}
            data={props.entries}
            getRowId={(entry) => getEntryId(entry)}
            fullWidth
            pageSize={props.entries.length > ENTRIES_PER_PAGE ? ENTRIES_PER_PAGE : undefined}
            onRowClick={props.canEditAny ? props.onEdit : undefined}
            rowClassName={(entry) => (getEntryId(entry) === props.selectedEntryId ? 'bg-fill-selected' : undefined)}
            empty={
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    No access control rules match these filters
                </Text>
            }
        />
    )
}
