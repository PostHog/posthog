import './DashboardTabs.css'

import clsx from 'clsx'
import { useEffect, useState } from 'react'

import { IconExternal, IconPlus } from '@posthog/icons'
import { Button, Input, Tabs, TabsList, TabsTrigger } from '@posthog/quill'

import { hasDangerousScheme } from 'lib/utils/url'

import { useGridDrag } from '../../grid/drag/gridDrag'
import { ActionContextMenu } from '../../menu/ActionContextMenu'
import type { MenuAction } from '../../menu/menuAction'
import { ACCENT_COLOR_KEYS, ACCENT_COLORS, type AccentColor } from '../../panels/core/accentColors'
import { type DashboardTab, isGridTab } from '../document/dashboardTypes'
import { useDashboard } from './dashboardContext'

function AccentColorDot({ color }: { color: AccentColor | undefined }): JSX.Element | null {
    return color ? (
        <span
            className="size-[7px] shrink-0 rounded-full"
            style={{ background: ACCENT_COLORS[color].css }}
            aria-hidden
        />
    ) : null
}

/**
 * Replaces the browser's faded copy of a dragged tab with one that looks lifted, like a dragged tile. The browser
 * snapshots the image when the drag starts, so the copy only has to exist until then.
 */
function setLiftedDragImage(event: React.DragEvent<HTMLElement>): void {
    const source = event.currentTarget
    const rect = source.getBoundingClientRect()
    const ghost = source.cloneNode(true) as HTMLElement
    ghost.classList.add('DashboardTabs__ghost')
    ghost.style.width = `${rect.width}px`
    ghost.style.height = `${rect.height}px`
    // Inside the dashboard, so it picks up the dashboard's colors.
    const host = source.closest('.DashboardV2') ?? document.body
    host.appendChild(ghost)
    event.dataTransfer.setDragImage(ghost, event.clientX - rect.left, event.clientY - rect.top)
    requestAnimationFrame(() => ghost.remove())
}

type TabDraft = {
    id: string
    title: string
}

type TabInsert = {
    id: string
    side: 'before' | 'after'
}

export function DashboardTabs(): JSX.Element | null {
    const { dashboard, activeTab, disabledReasonFor, can, onActiveTabChange, onEdit } = useDashboard()
    const { dropTarget } = useGridDrag()
    const [draft, setDraft] = useState<TabDraft | null>(null)
    const [draggedId, setDraggedId] = useState<string | null>(null)
    const [insert, setInsert] = useState<TabInsert | null>(null)
    // Kept in state, not a ref, so the wheel listener attaches whenever the row mounts, even after a render without it.
    const [scroller, setScroller] = useState<HTMLDivElement | null>(null)
    useEffect(() => {
        if (!scroller) {
            return
        }
        // Most mice only scroll vertically. Not passive, or the page scrolls down at the same time.
        const onWheel = (event: WheelEvent): void => {
            if (Math.abs(event.deltaX) >= Math.abs(event.deltaY) || scroller.scrollWidth <= scroller.clientWidth) {
                return
            }
            event.preventDefault()
            scroller.scrollLeft += event.deltaY
        }
        scroller.addEventListener('wheel', onWheel, { passive: false })
        return () => scroller.removeEventListener('wheel', onWheel)
    }, [scroller])
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

    const tabActions = (tab: DashboardTab, position: number): MenuAction[] => {
        const actions: MenuAction[] = []
        if (can('renameTab')) {
            actions.push({
                key: 'rename',
                label: 'Rename',
                dataAttr: 'dashboard-v2-rename-tab',
                disabledReason: renameDisabledReason,
                onSelect: () => startRename(tab.id, tab.title),
            })
        }
        if (canMove) {
            actions.push(
                {
                    key: 'move-left',
                    label: 'Move left',
                    dataAttr: 'dashboard-v2-move-tab-left',
                    disabledReason: position === 0 ? 'Already the first tab' : null,
                    onSelect: () => onEdit({ edit: 'moveTab', id: tab.id, before: tabIds[position - 1] ?? null }),
                },
                {
                    key: 'move-right',
                    label: 'Move right',
                    dataAttr: 'dashboard-v2-move-tab-right',
                    disabledReason: position === tabIds.length - 1 ? 'Already the last tab' : null,
                    onSelect: () => onEdit({ edit: 'moveTab', id: tab.id, before: tabIds[position + 2] ?? null }),
                }
            )
        }
        if (can('setTabColor')) {
            const setColor = (color: AccentColor | null) => (): void =>
                onEdit({ edit: 'setTabColor', id: tab.id, color })
            actions.push({
                key: 'color',
                label: 'Color',
                dataAttr: 'dashboard-v2-tab-color',
                disabledReason: disabledReasonFor('setTabColor'),
                group: 'display',
                choice: true,
                submenu: [
                    {
                        key: 'none',
                        label: 'None',
                        dataAttr: 'dashboard-v2-tab-color-none',
                        disabledReason: null,
                        checked: !tab.color,
                        onSelect: setColor(null),
                    },
                    ...ACCENT_COLOR_KEYS.map((color) => ({
                        key: color,
                        label: ACCENT_COLORS[color].label,
                        dataAttr: `dashboard-v2-tab-color-${color}`,
                        disabledReason: null,
                        checked: tab.color === color,
                        onSelect: setColor(color),
                    })),
                ],
            })
        }
        if (can('removeTab')) {
            actions.push({
                key: 'remove',
                label: 'Delete',
                dataAttr: 'dashboard-v2-delete-tab',
                disabledReason: removeDisabledReasonFor(tab),
                destructive: true,
                onSelect: () => onEdit({ edit: 'removeTab', id: tab.id }),
            })
        }
        return actions
    }

    if (dashboard.tabs.length === 1 && !can('addTab')) {
        return null
    }
    return (
        <div className="flex items-center gap-2 border-b">
            <Tabs
                ref={setScroller}
                className="DashboardTabs__scroller hide-scrollbar min-w-0 overflow-x-auto"
                style={
                    activeTab.color
                        ? ({ '--dv2-active-tab-color': ACCENT_COLORS[activeTab.color].css } as React.CSSProperties)
                        : undefined
                }
                value={activeTab.id}
                onValueChange={(value) => onActiveTabChange(String(value))}
            >
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
                        const insertClass = clsx(
                            insert?.id === tab.id && `DashboardTabs__tab--insert-${insert.side}`,
                            draggedId === tab.id && 'DashboardTabs__tab--dragging'
                        )
                        // Link tabs and grid tabs reorder the same way, so both take these.
                        const dragProps = {
                            draggable: canMove,
                            onDragStart: (event: React.DragEvent<HTMLElement>) => {
                                event.dataTransfer.effectAllowed = 'move'
                                event.dataTransfer.setData('text/plain', tab.title)
                                setLiftedDragImage(event)
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
                                <AccentColorDot color={tab.color} />
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
                                className={isDropTarget ? 'DashboardTabs__tab--drop-target' : insertClass}
                                onClick={(event) =>
                                    event.currentTarget.scrollIntoView({ block: 'nearest', inline: 'nearest' })
                                }
                                onDoubleClick={() => startRename(tab.id, tab.title)}
                                {...dragProps}
                            >
                                <AccentColorDot color={tab.color} />
                                {tab.title}
                            </TabsTrigger>
                        )
                        return (
                            <ActionContextMenu key={tab.id} actions={tabActions(tab, position)}>
                                {trigger}
                            </ActionContextMenu>
                        )
                    })}
                </TabsList>
            </Tabs>
            {can('addTab') && (
                <Button
                    size="xs"
                    className="shrink-0"
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
