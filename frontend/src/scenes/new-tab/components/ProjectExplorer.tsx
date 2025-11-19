import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { MouseEvent, useEffect, useMemo } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox } from 'lib/ui/ListBox/ListBox'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { joinPath, sortFilesAndFolders, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

import { getNewTabProjectTreeLogicProps, newTabSceneLogic } from '../newTabSceneLogic'

interface ExplorerRow {
    entry: FileSystemEntry
    depth: number
    isParentNavigation?: boolean
}

export function ProjectExplorer({ tabId }: { tabId: string }): JSX.Element | null {
    const projectTreeLogicProps = useMemo(() => getNewTabProjectTreeLogicProps(tabId), [tabId])
    const { folders, folderStates, users } = useValues(projectTreeLogic(projectTreeLogicProps))
    const { loadFolder } = useActions(projectTreeLogic(projectTreeLogicProps))
    const { activeExplorerFolderPath, explorerExpandedFolders, highlightedExplorerEntryPath } = useValues(
        newTabSceneLogic({ tabId })
    )
    const { setActiveExplorerFolderPath, toggleExplorerFolderExpansion, setHighlightedExplorerEntryPath } = useActions(
        newTabSceneLogic({ tabId })
    )

    useEffect(() => {
        if (activeExplorerFolderPath === null) {
            return
        }
        if (!folders[activeExplorerFolderPath] && folderStates[activeExplorerFolderPath] !== 'loading') {
            loadFolder(activeExplorerFolderPath)
        }
    }, [activeExplorerFolderPath, folders, folderStates, loadFolder])

    if (activeExplorerFolderPath === null) {
        return null
    }

    const currentEntries = folders[activeExplorerFolderPath] || []

    const buildRows = (entries: FileSystemEntry[], depth: number): ExplorerRow[] => {
        const sorted = [...entries].sort(sortFilesAndFolders)
        const rows: ExplorerRow[] = []
        for (const entry of sorted) {
            rows.push({ entry, depth })
            if (entry.type === 'folder' && explorerExpandedFolders[entry.path]) {
                const children = folders[entry.path] || []
                rows.push(...buildRows(children, depth + 1))
            }
        }
        return rows
    }

    const rows = buildRows(currentEntries, 0)
    const isLoadingCurrentFolder = folderStates[activeExplorerFolderPath] === 'loading'

    const breadcrumbSegments = splitPath(activeExplorerFolderPath)
    const parentBreadcrumbSegments = breadcrumbSegments.slice(0, -1)
    const parentFolderPath = joinPath(parentBreadcrumbSegments)
    const parentRow: ExplorerRow | null = breadcrumbSegments.length
        ? {
              entry: {
                  id: `__parent-${activeExplorerFolderPath || 'root'}`,
                  path: parentFolderPath,
                  type: 'folder',
              },
              depth: 0,
              isParentNavigation: true,
          }
        : null
    const displayRows = parentRow ? [parentRow, ...rows] : rows
    const handleToggleFolder = (path: string): void => {
        toggleExplorerFolderExpansion(path)
        if (!explorerExpandedFolders[path]) {
            loadFolder(path)
        }
    }

    const handleEntryActivate = (entry: FileSystemEntry, isParentNavigationRow?: boolean): void => {
        if (entry.type === 'folder') {
            if (isParentNavigationRow && activeExplorerFolderPath) {
                setHighlightedExplorerEntryPath(activeExplorerFolderPath)
            } else {
                setHighlightedExplorerEntryPath(null)
            }
            setActiveExplorerFolderPath(entry.path)
        } else if (entry.href) {
            setHighlightedExplorerEntryPath(null)
            router.actions.push(entry.href)
        }
    }

    const renderCreatedBy = (entry: FileSystemEntry): JSX.Element => {
        const createdById = entry.meta?.created_by
        const createdBy = createdById ? users[createdById] : undefined
        if (!createdBy) {
            return <span className="text-sm text-muted">—</span>
        }
        return (
            <span className="flex items-center gap-2 min-w-0">
                <ProfilePicture user={createdBy} size="sm" className="shrink-0" />
                <span className="text-sm truncate text-primary">
                    {createdBy.first_name || createdBy.email || 'Unknown'}
                </span>
            </span>
        )
    }

    const renderCreatedAt = (entry: FileSystemEntry): string =>
        entry.created_at ? dayjs(entry.created_at).format('MMM D, YYYY') : '—'

    return (
        <div className="flex flex-col gap-3 p-3">
            <div className="rounded bg-bg-300 overflow-hidden">
                <div className="grid grid-cols-[minmax(0,1fr)_200px_160px] border-b border-border px-3 py-2 text-xs uppercase text-muted">
                    <div className="pr-3 pl-6">Name</div>
                    <div className="px-3 pl-6">Created by</div>
                    <div className="px-3 pl-6">Created at</div>
                </div>
                {isLoadingCurrentFolder && rows.length === 0 ? (
                    <div className="flex items-center gap-2 px-3 py-4 text-muted">
                        <Spinner /> Loading folder...
                    </div>
                ) : null}
                <ListBox.Group groupId="project-explorer">
                    {displayRows.map(({ entry, depth, isParentNavigation }, rowIndex) => {
                        const isParentNavigationRow = !!isParentNavigation
                        const isFolder = entry.type === 'folder'
                        const isExpandableFolder = isFolder && !isParentNavigationRow
                        const isExpanded = isExpandableFolder && !!explorerExpandedFolders[entry.path]
                        const icon = iconForType((entry.type as FileSystemIconType) || 'default_icon_type')
                        const focusBase = String(entry.id ?? entry.path ?? rowIndex)
                        const nameLabel = isParentNavigationRow ? '..' : splitPath(entry.path).pop() || entry.path
                        const isHighlighted = highlightedExplorerEntryPath === entry.path
                        const handleRowClick = (event: MouseEvent<HTMLElement>): void => {
                            event.preventDefault()
                            handleEntryActivate(entry, isParentNavigationRow)
                        }
                        return (
                            <ListBox.Item
                                asChild
                                row={rowIndex}
                                column={0}
                                focusKey={`${focusBase}-row`}
                                index={rowIndex}
                                key={`${entry.id ?? entry.path}-${rowIndex}`}
                            >
                                <Link
                                    to={entry.href || '#'}
                                    className={clsx(
                                        'grid grid-cols-[minmax(0,1fr)_200px_160px] border-t border-border text-primary no-underline focus-visible:outline-none first:border-t-0 data-[focused=true]:bg-primary-alt-highlight data-[focused=true]:text-primary',
                                        isHighlighted && 'bg-primary-alt-highlight text-primary'
                                    )}
                                    onClick={handleRowClick}
                                >
                                    <div
                                        className="flex items-center gap-2 px-3 py-2 min-w-0 text-sm"
                                        style={{ paddingLeft: 12 + depth * 16 }}
                                    >
                                        {isExpandableFolder ? (
                                            <ButtonPrimitive
                                                size="xs"
                                                iconOnly
                                                tabIndex={-1}
                                                className="shrink-0"
                                                onMouseDown={(event) => event.preventDefault()}
                                                onClick={(event) => {
                                                    event.stopPropagation()
                                                    event.preventDefault()
                                                    handleToggleFolder(entry.path)
                                                }}
                                                aria-label={isExpanded ? 'Collapse folder' : 'Expand folder'}
                                            >
                                                <IconChevronRight
                                                    className={`size-3 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                                                />
                                            </ButtonPrimitive>
                                        ) : (
                                            <span className="w-4" />
                                        )}
                                        <span className="shrink-0 text-primary">{icon}</span>
                                        <span className="truncate">{nameLabel}</span>
                                        {isExpandableFolder && folderStates[entry.path] === 'loading' ? (
                                            <Spinner className="size-3" />
                                        ) : null}
                                    </div>
                                    <div className="flex items-center gap-2 px-3 py-2 min-w-0 text-sm text-primary">
                                        {renderCreatedBy(entry)}
                                    </div>
                                    <div className="flex items-center gap-2 px-3 py-2 min-w-0 text-sm text-muted">
                                        {renderCreatedAt(entry)}
                                    </div>
                                </Link>
                            </ListBox.Item>
                        )
                    })}
                    {!isLoadingCurrentFolder && rows.length === 0 ? (
                        <div className="px-3 py-4 text-sm text-muted border-t border-border">
                            No files in this folder yet.
                        </div>
                    ) : null}
                </ListBox.Group>
            </div>
        </div>
    )
}
