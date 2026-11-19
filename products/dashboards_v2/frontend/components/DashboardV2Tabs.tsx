import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { Button, Input, Tabs, TabsList, TabsTrigger } from '@posthog/quill'

import { dashboardV2Logic } from '../dashboardV2Logic'

export function DashboardV2Tabs(): JSX.Element | null {
    const { dashboard, activeTab, canEditLayout, dropTarget } = useValues(dashboardV2Logic)
    const { setActiveTab, applyDashboardEdit } = useActions(dashboardV2Logic)
    const [draft, setDraft] = useState<string | null>(null)

    const commitRename = (): void => {
        if (draft !== null && draft.trim() && draft.trim() !== activeTab.title) {
            applyDashboardEdit({ edit: 'renameTab', id: activeTab.id, title: draft.trim() })
        }
        setDraft(null)
    }

    if (dashboard.tabs.length === 1 && !canEditLayout) {
        return null
    }
    return (
        <div className="flex items-center gap-2 border-b">
            <Tabs
                value={activeTab.id}
                onValueChange={(value) => {
                    setDraft(null)
                    setActiveTab(String(value))
                }}
            >
                <TabsList variant="line" data-attr="dashboard-v2-tabs">
                    {dashboard.tabs.map((tab) => (
                        // A tile dropped on a tab moves to that tab; the drag looks for `data-dv2-tab`.
                        <TabsTrigger
                            key={tab.id}
                            value={tab.id}
                            data-dv2-tab={tab.id === activeTab.id ? undefined : tab.id}
                            className={
                                dropTarget?.grid === tab.id && tab.id !== activeTab.id
                                    ? 'DashboardV2__tab--drop-target'
                                    : undefined
                            }
                        >
                            {tab.title}
                        </TabsTrigger>
                    ))}
                </TabsList>
            </Tabs>
            {canEditLayout && draft !== null && (
                <Input
                    autoFocus
                    className="h-6 w-48 text-sm"
                    aria-label="Tab name"
                    data-attr="dashboard-v2-tab-name"
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    onBlur={commitRename}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                            commitRename()
                        } else if (event.key === 'Escape') {
                            setDraft(null)
                        }
                    }}
                />
            )}
            {canEditLayout && draft === null && (
                <>
                    <Button
                        size="icon-xs"
                        aria-label="Rename this tab"
                        tooltip="Rename this tab"
                        data-attr="dashboard-v2-rename-tab"
                        onClick={() => setDraft(activeTab.title)}
                    >
                        <IconPencil />
                    </Button>
                    <Button
                        size="icon-xs"
                        aria-label="Delete this tab"
                        tooltip="Delete this tab"
                        data-attr="dashboard-v2-delete-tab"
                        disabledReason={dashboard.tabs.length === 1 ? 'A dashboard needs at least one tab' : undefined}
                        onClick={() => applyDashboardEdit({ edit: 'removeTab', id: activeTab.id })}
                    >
                        <IconTrash />
                    </Button>
                    <Button
                        size="xs"
                        data-attr="dashboard-v2-add-tab"
                        onClick={() => applyDashboardEdit({ edit: 'addTab', title: 'New tab' })}
                    >
                        <IconPlus />
                        Tab
                    </Button>
                </>
            )}
        </div>
    )
}
