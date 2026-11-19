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

/** Where a tab lands once it is taken out of the list, so `moveTab` can insert it there. */
function insertIndex(tabIds: string[], draggedId: string, insert: TabInsert): number {
    const target = tabIds.indexOf(insert.id) + (insert.side === 'after' ? 1 : 0)
    return tabIds.indexOf(draggedId) < target ? target - 1 : target
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
        if (draggedId !== null && insert !== null && insert.id !== draggedId) {
            applyDashboardEdit({ edit: 'moveTab', id: draggedId, index: insertIndex(tabIds, draggedId, insert) })
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
                    {dashboard.tabs.map((tab) => {
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
                            draggedId !== null && insert?.id === tab.id && insert.id !== draggedId
                                ? `DashboardV2__tab--insert-${insert.side}`
                                : undefined
                        const position = tabIds.indexOf(tab.id)
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
                                    {canMove && (
                                        <>
                                            <ContextMenuItem
                                                data-attr="dashboard-v2-move-tab-left"
                                                disabled={position === 0}
                                                onClick={() =>
                                                    applyDashboardEdit({
                                                        edit: 'moveTab',
                                                        id: tab.id,
                                                        index: position - 1,
                                                    })
                                                }
                                            >
                                                <IconArrowLeft />
                                                Move left
                                            </ContextMenuItem>
                                            <ContextMenuItem
                                                data-attr="dashboard-v2-move-tab-right"
                                                disabled={position === tabIds.length - 1}
                                                onClick={() =>
                                                    applyDashboardEdit({
                                                        edit: 'moveTab',
                                                        id: tab.id,
                                                        index: position + 1,
                                                    })
                                                }
                                            >
                                                <IconArrowRight />
                                                Move right
                                            </ContextMenuItem>
                                        </>
                                    )}
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
