import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Badge, Button, Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'

import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'

import { QuillHistoryPanel } from './QuillHistoryPanel'
import { QuillSchemaPanel } from './QuillSchemaPanel'
import { QuillVariablesPanel } from './QuillVariablesPanel'
import { SqlEditorInspectorTab } from './sqlEditorLayout'
import { sqlEditorLayoutLogic } from './sqlEditorLayoutLogic'
import { INSPECTOR_TAB_LABELS } from './sqlEditorWorkspaceCopy'

/**
 * The editor's side panel. Which tabs it shows, in what order, comes from the person's layout, so
 * the panel only knows how to draw each tab.
 */
export function QuillSqlEditorInspector({
    tabId,
    floating = false,
}: {
    tabId: string
    /** The panel floats over the query on a narrow workspace, and closing it only dismisses it. */
    floating?: boolean
}): JSX.Element {
    const { layout } = useValues(sqlEditorLayoutLogic)
    const { setInspectorTab, setInspectorOpen, setInspectorOverlayOpen } = useActions(sqlEditorLayoutLogic)
    const { editingView } = useValues(sqlEditorLogic)
    const { variablesUsedInQuery } = useValues(variablesLogic)

    const renderPanel = (tab: SqlEditorInspectorTab): JSX.Element => {
        switch (tab) {
            case 'schema':
                return <QuillSchemaPanel tabId={tabId} />
            case 'variables':
                return <QuillVariablesPanel disabledReason={editingView ? "Views can't use variables." : undefined} />
            case 'history':
                return <QuillHistoryPanel />
        }
    }

    return (
        <Tabs
            value={layout.inspector.activeTab}
            onValueChange={(tab) => setInspectorTab(tab as SqlEditorInspectorTab)}
            className="flex h-full min-h-0 flex-col gap-0 bg-background"
        >
            <div className="flex h-10 shrink-0 items-center gap-1 border-b ps-1 pe-1.5">
                <TabsList variant="line" className="h-10 min-w-0">
                    {layout.inspector.tabs.map((tab) => (
                        <TabsTrigger key={tab} value={tab} data-attr={`sql-editor-inspector-tab-${tab}`}>
                            {INSPECTOR_TAB_LABELS[tab]}
                            {tab === 'variables' && variablesUsedInQuery.length > 0 ? (
                                <Badge aria-label={`${variablesUsedInQuery.length} in this query`}>
                                    {variablesUsedInQuery.length}
                                </Badge>
                            ) : null}
                        </TabsTrigger>
                    ))}
                </TabsList>
                <Button
                    size="icon-sm"
                    className="ms-auto"
                    aria-label="Close side panel"
                    tooltip="Close side panel"
                    onClick={() => (floating ? setInspectorOverlayOpen(false) : setInspectorOpen(false))}
                    data-attr="sql-editor-inspector-close"
                >
                    <IconX />
                </Button>
            </div>
            {layout.inspector.tabs.map((tab) => (
                <TabsContent key={tab} value={tab} className="min-h-0 flex-1">
                    {renderPanel(tab)}
                </TabsContent>
            ))}
        </Tabs>
    )
}
