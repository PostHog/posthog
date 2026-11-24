import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
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

import { dashboardV2Logic } from '../dashboardV2Logic'

interface TabDraft {
    id: string
    title: string
}

interface TabInsert {
    id: string
    side: 'before' | 'after'
}

export function DashboardV2Tabs(): JSX.Element | null {
    const { dashboard, activeTab, hasPermission, dropTarget, disabledReasonFor } = useValues(dashboardV2Logic)
    const { setActiveTab, applyDashboardEdit } = useActions(dashboardV2Logic)
    const [draft, setDraft] = useState<TabDraft | null>(null)
    const [draggedId, setDraggedId] = useState<string | null>(null)
    const [insert, setInsert] = useState<TabInsert | null>(null)
    const canMove = hasPermission('moveTab')
    const tabIds = dashboard.tabs.map((tab) => tab.id)

    const endDrag = (): void => {
        setDraggedId(null)
        setInsert(null)
    }

    const dropTab = (): void => {
        if (draggedId !== null && insert !== null) {
            const before = insert.side === 'before' ? insert.id : (tabIds[tabIds.indexOf(insert.id) + 1] ?? null)
            applyDashboardEdit({ edit: 'moveTab', id: draggedId, before })
        }
        endDrag()
    }

    const renameDisabledReason = disabledReasonFor('renameTab')
    const addDisabledReason = disabledReasonFor('addTab')
    const removeDisabledReason =
        disabledReasonFor('removeTab') ?? (dashboard.tabs.length === 1 ? 'A dashboard needs at least one tab' : null)

    const commitRename = (): void => {
        if (draft === null) {
            return
        }
        const title = draft.title.trim()
        const original = dashboard.tabs.find((tab) => tab.id === draft.id)?.title
        if (original !== undefined && title && title !== original) {
            applyDashboardEdit({ edit: 'renameTab', id: draft.id, title })
        }
        setDraft(null)
    }

    const startRename = (id: string, title: string): void => {
        if (renameDisabledReason === null) {
            setDraft({ id, title })
        }
    }

    if (dashboard.tabs.length === 1 && !hasPermission('addTab')) {
        return null
    }
    return (
        <div className="flex items-center gap-2 border-b">
            <Tabs value={activeTab.id} onValueChange={(value) => setActiveTab(String(value))}>
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
                        // A tile dropped on a tab moves to that tab; the drag looks for `data-dv2-tab`.
                        const trigger = (
                            <TabsTrigger
                                key={tab.id}
                                value={tab.id}
                                data-dv2-tab={tab.id === activeTab.id ? undefined : tab.id}
                                className={isDropTarget ? 'DashboardV2__tab--drop-target' : insertClass}
                                onDoubleClick={() => startRename(tab.id, tab.title)}
                                draggable={canMove}
                                onDragStart={(event) => {
                                    event.dataTransfer.effectAllowed = 'move'
                                    event.dataTransfer.setData('text/plain', tab.title)
                                    setDraggedId(tab.id)
                                }}
                                onDragOver={(event) => {
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
                                }}
                                onDrop={(event) => {
                                    event.preventDefault()
                                    dropTab()
                                }}
                                onDragEnd={endDrag}
                            >
                                {tab.title}
                            </TabsTrigger>
                        )
                        if (!hasPermission('renameTab') && !hasPermission('removeTab') && !canMove) {
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
                                                onClick={() =>
                                                    applyDashboardEdit({ edit: 'moveTab', id: tab.id, before })
                                                }
                                            >
                                                <Icon />
                                                {label}
                                            </ContextMenuItem>
                                        ))}
                                    <ContextMenuItem
                                        variant="destructive"
                                        data-attr="dashboard-v2-delete-tab"
                                        disabled={removeDisabledReason !== null}
                                        onClick={() => applyDashboardEdit({ edit: 'removeTab', id: tab.id })}
                                    >
                                        <IconTrash />
                                        <span className="flex flex-col items-start">
                                            Delete
                                            {removeDisabledReason && (
                                                <span className="text-xs text-muted-foreground">
                                                    {removeDisabledReason}
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
            {hasPermission('addTab') && (
                <Button
                    size="xs"
                    data-attr="dashboard-v2-add-tab"
                    disabledReason={addDisabledReason ?? undefined}
                    onClick={() => applyDashboardEdit({ edit: 'addTab', title: 'New tab' })}
                >
                    <IconPlus />
                    Tab
                </Button>
            )}
        </div>
    )
}
