import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox } from 'lib/ui/ListBox/ListBox'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { sortFilesAndFolders, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

import { getNewTabProjectTreeLogicProps, newTabSceneLogic } from '../newTabSceneLogic'

interface ExplorerRow {
    entry: FileSystemEntry
    depth: number
}

export function ProjectExplorer({ tabId }: { tabId: string }): JSX.Element | null {
    const projectTreeLogicProps = useMemo(() => getNewTabProjectTreeLogicProps(tabId), [tabId])
    const { folders, folderStates, users } = useValues(projectTreeLogic(projectTreeLogicProps))
    const { loadFolder } = useActions(projectTreeLogic(projectTreeLogicProps))
    const { activeExplorerFolderPath, explorerExpandedFolders } = useValues(newTabSceneLogic({ tabId }))
    const { setActiveExplorerFolderPath, toggleExplorerFolderExpansion } = useActions(newTabSceneLogic({ tabId }))

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
    const breadcrumbs = [
        { label: 'Project root', path: '' },
        ...breadcrumbSegments.map((segment, index) => ({
            label: segment,
            path: breadcrumbSegments.slice(0, index + 1).join('/'),
        })),
    ]

    const handleToggleFolder = (path: string): void => {
        toggleExplorerFolderExpansion(path)
        if (!explorerExpandedFolders[path]) {
            loadFolder(path)
        }
    }

    const handleEntryActivate = (entry: FileSystemEntry): void => {
        if (entry.type === 'folder') {
            setActiveExplorerFolderPath(entry.path)
        } else if (entry.href) {
            router.actions.push(entry.href)
        }
    }

    const renderCreatedBy = (entry: FileSystemEntry): JSX.Element => {
        const createdById = entry.meta?.created_by
        const createdBy = createdById ? users[createdById] : undefined
        if (!createdBy) {
            return <span className="text-sm text-muted">Unknown</span>
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
        <div className="flex flex-col gap-3 border border-border rounded p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-1 text-sm font-medium">
                    {breadcrumbs.map((crumb, index) => (
                        <span key={`${crumb.path}-${index}`} className="flex items-center gap-1">
                            <button
                                type="button"
                                className="text-primary hover:underline"
                                onClick={() => setActiveExplorerFolderPath(crumb.path)}
                            >
                                {crumb.label || 'Untitled'}
                            </button>
                            {index < breadcrumbs.length - 1 && <span className="text-muted">/</span>}
                        </span>
                    ))}
                </div>
                <ButtonPrimitive size="xs" onClick={() => setActiveExplorerFolderPath(null)}>
                    ← Back to results
                </ButtonPrimitive>
            </div>
            <div className="rounded border bg-bg-300 overflow-hidden">
                <div className="grid grid-cols-[minmax(0,1fr)_200px_160px] px-3 py-2 text-xs uppercase text-muted">
                    <span>Name</span>
                    <span>Created by</span>
                    <span>Created at</span>
                </div>
                {isLoadingCurrentFolder && rows.length === 0 ? (
                    <div className="flex items-center gap-2 px-3 py-4 text-muted">
                        <Spinner /> Loading folder...
                    </div>
                ) : null}
                {!isLoadingCurrentFolder && rows.length === 0 ? (
                    <div className="px-3 py-4 text-sm text-muted">No files in this folder yet.</div>
                ) : null}
                <ListBox.Group groupId="project-explorer">
                    {rows.map(({ entry, depth }, rowIndex) => {
                        const isFolder = entry.type === 'folder'
                        const isExpanded = !!explorerExpandedFolders[entry.path]
                        const icon = iconForType((entry.type as FileSystemIconType) || 'default_icon_type')
                        const focusBase = String(entry.id ?? entry.path ?? rowIndex)
                        const baseCellClasses =
                            'flex items-center gap-2 px-3 py-2 min-w-0 border-t border-border text-sm data-[focused=true]:bg-bg-300 data-[focused=true]:text-primary'
                        const nameLabel = splitPath(entry.path).pop() || entry.path
                        return (
                            <div
                                key={`${entry.id ?? entry.path}-${rowIndex}`}
                                className="grid grid-cols-[minmax(0,1fr)_200px_160px]"
                            >
                                <ListBox.Item asChild row={rowIndex} column={0} focusKey={`${focusBase}-name`}>
                                    <div
                                        className={`${baseCellClasses} text-primary`}
                                        style={{ paddingLeft: 12 + depth * 16 }}
                                        onDoubleClick={() => handleEntryActivate(entry)}
                                        onKeyDown={(event) => {
                                            if (event.key === 'Enter') {
                                                event.preventDefault()
                                                handleEntryActivate(entry)
                                            }
                                        }}
                                    >
                                        {isFolder ? (
                                            <ButtonPrimitive
                                                size="xs"
                                                iconOnly
                                                tabIndex={-1}
                                                className="shrink-0"
                                                onMouseDown={(event) => event.preventDefault()}
                                                onClick={(event) => {
                                                    event.stopPropagation()
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
                                        <span
                                            className="truncate cursor-pointer"
                                            onClick={(event) => {
                                                event.stopPropagation()
                                                handleEntryActivate(entry)
                                            }}
                                        >
                                            {nameLabel}
                                        </span>
                                        {isFolder && folderStates[entry.path] === 'loading' ? (
                                            <Spinner className="size-3" />
                                        ) : null}
                                    </div>
                                </ListBox.Item>
                                <ListBox.Item asChild row={rowIndex} column={1} focusKey={`${focusBase}-created-by`}>
                                    <div className={`${baseCellClasses} text-primary`}>{renderCreatedBy(entry)}</div>
                                </ListBox.Item>
                                <ListBox.Item asChild row={rowIndex} column={2} focusKey={`${focusBase}-created-at`}>
                                    <div className={`${baseCellClasses} text-muted`}>{renderCreatedAt(entry)}</div>
                                </ListBox.Item>
                            </div>
                        )
                    })}
                </ListBox.Group>
            </div>
        </div>
    )
}
