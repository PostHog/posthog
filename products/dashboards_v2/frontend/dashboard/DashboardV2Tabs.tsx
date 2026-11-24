import clsx from 'clsx'
import { useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconExternal, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import {
    Button,
    ContextMenu,
    ContextMenuContent,
    ContextMenuItem,
    ContextMenuTrigger,
    Input,
    Tabs,
    TabsList,
    TabsTrigger,
} from '@posthog/quill'

import { hasDangerousScheme } from 'lib/utils/url'

import { useGridDrag } from '../grid/gridDrag'
import { type DashboardTab, isGridTab } from './dashboardTypes'
import { useDashboardV2 } from './dashboardV2Context'

interface TabDraft {
    id: string
    title: string
}

interface TabInsert {
    id: string
    side: 'before' | 'after'
}

export function DashboardV2Tabs(): JSX.Element | null {
    const { dashboard, activeTab, disabledReasonFor, can, onActiveTabChange, onEdit } = useDashboardV2()
    const { dropTarget } = useGridDrag()
    const [draft, setDraft] = useState<TabDraft | null>(null)
    const [draggedId, setDraggedId] = useState<string | null>(null)
    const [insert, setInsert] = useState<TabInsert | null>(null)
    const canMove = can('moveTab')
    const tabIds = dashboard.tabs.map((tab) => tab.id)

    const endDrag = (): void => {
        setDraggedId(null)
        setInsert(null)
    }

    const dropTab = (): void => {
        if (draggedId !== null && insert !== null) {
            const before = insert.side === 'before' ? insert.id : (tabIds[tabIds.indexOf(insert.id) + 1] ?? null)
            onEdit({ edit: 'moveTab', id: draggedId, before })
        }
        endDrag()
    }

    const renameDisabledReason = disabledReasonFor('renameTab')
    const addDisabledReason = disabledReasonFor('addTab')
    const lastGridTab = dashboard.tabs.filter(isGridTab).length === 1
    const removeDisabledReasonFor = (tab: DashboardTab): string | null =>
        disabledReasonFor('removeTab') ??
        (lastGridTab && isGridTab(tab) ? 'A dashboard needs at least one tab with tiles' : null)

    const commitRename = (): void => {
        if (draft === null) {
            return
        }
        const title = draft.title.trim()
        const original = dashboard.tabs.find((tab) => tab.id === draft.id)?.title
        if (original !== undefined && title && title !== original) {
            onEdit({ edit: 'renameTab', id: draft.id, title })
        }
        setDraft(null)
    }

    const startRename = (id: string, title: string): void => {
        if (renameDisabledReason === null) {
            setDraft({ id, title })
        }
    }

    if (dashboard.tabs.length === 1 && !can('addTab')) {
        return null
    }
    return (
        <div className="flex items-center gap-2 border-b">
            <Tabs value={activeTab.id} onValueChange={(value) => onActiveTabChange(String(value))}>
                <TabsList variant="line" data-attr="dashboard-v2-tabs">
                    {dashboard.tabs.map((tab, position) => {
                        if (draft?.id === tab.id) {
                            return (
                                <Input
                                    key={tab.id}
                                    autoFocus
                                    className="h-6 text-sm"
                                    style={{ width: `${Math.max(draft.title.length, 4) + 3}ch` }}
                                    aria-label="Tab name"
                                    data-attr="dashboard-v2-tab-name"
                                    value={draft.title}
                                    onFocus={(event) => event.target.select()}
                                    onChange={(event) => setDraft({ id: tab.id, title: event.target.value })}
                                    onBlur={commitRename}
                                    onKeyDown={(event) => {
                                        // The tab list moves focus on these keys, which would blur and end the rename.
                                        if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
                                            event.stopPropagation()
                                        }
                                        if (event.key === 'Enter') {
                                            commitRename()
                                        } else if (event.key === 'Escape') {
                                            setDraft(null)
                                        }
                                    }}
                                />
                            )
                        }
                        const isDropTarget = dropTarget?.grid === tab.id && tab.id !== activeTab.id
                        const insertClass =
                            insert?.id === tab.id ? `DashboardV2__tab--insert-${insert.side}` : undefined
                        const moves = [
                            {
                                key: 'left',
                                label: 'Move left',
                                Icon: IconArrowLeft,
                                disabled: position === 0,
                                before: tabIds[position - 1] ?? null,
                            },
                            {
                                key: 'right',
                                label: 'Move right',
                                Icon: IconArrowRight,
                                disabled: position === tabIds.length - 1,
                                before: tabIds[position + 2] ?? null,
                            },
                        ]
                        // Link tabs and grid tabs reorder the same way, so both take these.
                        const dragProps = {
                            draggable: canMove,
                            onDragStart: (event: React.DragEvent<HTMLElement>) => {
                                event.dataTransfer.effectAllowed = 'move'
                                event.dataTransfer.setData('text/plain', tab.title)
                                setDraggedId(tab.id)
                            },
                            onDragOver: (event: React.DragEvent<HTMLElement>) => {
                                if (draggedId === null) {
                                    return
                                }
                                if (tab.id === draggedId) {
                                    setInsert(null)
                                    return
                                }
                                event.preventDefault()
                                const rect = event.currentTarget.getBoundingClientRect()
                                const side = event.clientX < rect.left + rect.width / 2 ? 'before' : 'after'
                                if (insert?.id !== tab.id || insert.side !== side) {
                                    setInsert({ id: tab.id, side })
                                }
                            },
                            onDrop: (event: React.DragEvent<HTMLElement>) => {
                                event.preventDefault()
                                dropTab()
                            },
                            onDragEnd: endDrag,
                        }
                        // A link tab opens its page in a new browser tab, so the dashboard stays open. It holds
                        // no tiles, so it is not a drop target and does not take part in the tab list's arrow keys.
                        const link = !isGridTab(tab) && (
                            // Lemon's Link adds a drag-to-notebook handler that swallows the drag that reorders tabs.
                            // eslint-disable-next-line react/forbid-elements
                            <a
                                key={tab.id}
                                href={hasDangerousScheme(tab.href) ? undefined : tab.href}
                                target="_blank"
                                rel="noopener noreferrer"
                                className={clsx(
                                    'quill-tabs__trigger inline-flex items-center gap-1.5 whitespace-nowrap px-2 text-sm',
                                    insertClass
                                )}
                                data-attr="dashboard-v2-link-tab"
                                {...dragProps}
                            >
                                {tab.title}
                                <IconExternal className="size-3 text-secondary" aria-hidden />
                            </a>
                        )
                        // A tile dropped on a tab moves to that tab; the drag looks for `data-dv2-tab`.
                        const trigger = link || (
                            <TabsTrigger
                                key={tab.id}
                                value={tab.id}
                                data-dv2-tab={tab.id === activeTab.id ? undefined : tab.id}
                                className={isDropTarget ? 'DashboardV2__tab--drop-target' : insertClass}
                                onDoubleClick={() => startRename(tab.id, tab.title)}
                                {...dragProps}
                            >
                                {tab.title}
                            </TabsTrigger>
                        )
                        if (!can('renameTab') && !can('removeTab') && !canMove) {
                            return trigger
                        }
                        return (
                            <ContextMenu key={tab.id}>
                                <ContextMenuTrigger render={trigger} />
                                {/* Returning focus to the tab would blur the rename input straight away. */}
                                <ContextMenuContent data-attr="dashboard-v2-tab-menu" finalFocus={false}>
                                    <ContextMenuItem
                                        data-attr="dashboard-v2-rename-tab"
                                        disabled={renameDisabledReason !== null}
                                        onClick={() => startRename(tab.id, tab.title)}
                                    >
                                        <IconPencil />
                                        Rename
                                    </ContextMenuItem>
                                    {canMove &&
                                        moves.map(({ key, label, Icon, disabled, before }) => (
                                            <ContextMenuItem
                                                key={key}
                                                data-attr={`dashboard-v2-move-tab-${key}`}
                                                disabled={disabled}
                                                onClick={() => onEdit({ edit: 'moveTab', id: tab.id, before })}
                                            >
                                                <Icon />
                                                {label}
                                            </ContextMenuItem>
                                        ))}
                                    <ContextMenuItem
                                        variant="destructive"
                                        data-attr="dashboard-v2-delete-tab"
                                        disabled={removeDisabledReasonFor(tab) !== null}
                                        onClick={() => onEdit({ edit: 'removeTab', id: tab.id })}
                                    >
                                        <IconTrash />
                                        <span className="flex flex-col items-start">
                                            Delete
                                            {removeDisabledReasonFor(tab) && (
                                                <span className="text-xs text-muted-foreground">
                                                    {removeDisabledReasonFor(tab)}
                                                </span>
                                            )}
                                        </span>
                                    </ContextMenuItem>
                                </ContextMenuContent>
                            </ContextMenu>
                        )
                    })}
                </TabsList>
            </Tabs>
            {can('addTab') && (
                <Button
                    size="xs"
                    data-attr="dashboard-v2-add-tab"
                    disabledReason={addDisabledReason ?? undefined}
                    onClick={() => onEdit({ edit: 'addTab', title: 'New tab' })}
                >
                    <IconPlus />
                    Tab
                </Button>
            )}
        </div>
    )
}
