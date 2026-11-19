import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
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

export function DashboardV2Tabs(): JSX.Element | null {
    const { dashboard, activeTab, canEditLayout, dropTarget, disabledReasonFor } = useValues(dashboardV2Logic)
    const { setActiveTab, applyDashboardEdit } = useActions(dashboardV2Logic)
    const [draft, setDraft] = useState<TabDraft | null>(null)

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

    if (dashboard.tabs.length === 1 && !canEditLayout) {
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
                        // A tile dropped on a tab moves to that tab; the drag looks for `data-dv2-tab`.
                        const trigger = (
                            <TabsTrigger
                                key={tab.id}
                                value={tab.id}
                                data-dv2-tab={tab.id === activeTab.id ? undefined : tab.id}
                                className={isDropTarget ? 'DashboardV2__tab--drop-target' : undefined}
                                onDoubleClick={() => startRename(tab.id, tab.title)}
                            >
                                {tab.title}
                            </TabsTrigger>
                        )
                        if (!canEditLayout) {
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
            {canEditLayout && (
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
