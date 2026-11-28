import { Monaco } from '@monaco-editor/react'
import { useActions, useValues } from 'kea'
import type { editor as importedEditor } from 'monaco-editor'
import { memo, useRef } from 'react'

import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@posthog/quill'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { OutputPane } from 'scenes/data-warehouse/editor/OutputPane'
import { QueryPane } from 'scenes/data-warehouse/editor/QueryPane'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { useExecuteSqlToolBridge } from 'scenes/data-warehouse/editor/useExecuteSqlToolBridge'
import { useQueryPaneProps } from 'scenes/data-warehouse/editor/useQueryPaneProps'

import { NewVariableModal } from '~/queries/nodes/DataVisualization/Components/Variables/NewVariableModal'

import { VimrcModal } from 'products/data_warehouse/frontend/shared/components/VimrcModal'

import { QuillQueryToolbar } from './QuillQueryToolbar'
import { QuillSqlEditorInspector } from './QuillSqlEditorInspector'
import { sqlEditorLayoutLogic } from './sqlEditorLayoutLogic'

/**
 * Below this width the side panel would squeeze the query and results too far, so it floats over
 * them instead of taking a column. A 1280px laptop with PostHog AI docked leaves about 700px here.
 */
const DOCKED_INSPECTOR_MIN_WORKSPACE_WIDTH = 760

// The workspace renders on every keystroke, because the query pane reads the query text. The
// results pane doesn't depend on it, so memo keeps the grid and chart off that path.
const WorkspaceResults = memo(function WorkspaceResults({
    tabId,
    onShareTab,
}: {
    tabId: string
    onShareTab?: () => void
}): JSX.Element | null {
    const { finishedLoading } = useValues(sqlEditorLogic)
    // The logic sets finishedLoading while a tab tears down, and the pane must not render against it.
    return finishedLoading ? null : <OutputPane tabId={tabId} onShareTab={onShareTab} />
})

export interface QuillSqlEditorWorkspaceProps {
    tabId: string
    onSetMonacoAndEditor: (monaco: Monaco, editor: importedEditor.IStandaloneCodeEditor) => void
    onShareTab?: () => void
}

export function QuillSqlEditorWorkspace({
    tabId,
    onSetMonacoAndEditor,
    onShareTab,
}: QuillSqlEditorWorkspaceProps): JSX.Element {
    const codeEditorKey = `hogql-editor-${tabId}`
    const { layout, workspaceSizes, editorSizes, inspectorOverlayOpen } = useValues(sqlEditorLayoutLogic)
    const { setWorkspaceSizes, setEditorSizes, setInspectorOverlayOpen } = useActions(sqlEditorLayoutLogic)
    const queryPaneProps = useQueryPaneProps({ tabId, codeEditorKey, onSetMonacoAndEditor })
    useExecuteSqlToolBridge(tabId, true)

    const workspaceRef = useRef<HTMLDivElement>(null)
    const { width = Infinity } = useResizeObserver({ ref: workspaceRef })
    const docked = width >= DOCKED_INSPECTOR_MIN_WORKSPACE_WIDTH
    const inspectorOpen = layout.inspector.open
    const inspectorOnLeft = layout.inspector.side === 'left'

    const inspectorPanel =
        inspectorOpen && docked ? (
            <ResizablePanel id="inspector" defaultSize="18rem" minSize="14rem" maxSize="40%">
                <QuillSqlEditorInspector tabId={tabId} />
            </ResizablePanel>
        ) : null

    const queryAndResults = (
        <ResizablePanelGroup
            // A new id when the results move makes the group start from its defaults rather than
            // from sizes that belonged to the other orientation.
            key={layout.results.placement}
            orientation={layout.results.placement === 'below' ? 'vertical' : 'horizontal'}
            defaultLayout={editorSizes ?? undefined}
            onLayoutChanged={setEditorSizes}
        >
            <ResizablePanel id="query" defaultSize={40} minSize="6rem">
                <QueryPane {...queryPaneProps} constrainHeight={false} />
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel id="results" defaultSize={60} minSize="8rem" className="flex min-h-0 flex-col">
                <WorkspaceResults tabId={tabId} onShareTab={onShareTab} />
            </ResizablePanel>
        </ResizablePanelGroup>
    )

    return (
        <QuillSurfaceContext.Provider value={true}>
            <div
                ref={workspaceRef}
                data-quill
                data-attr="editor-scene"
                className="@container/sql-workspace relative flex h-full min-h-0 w-full min-w-0 flex-col bg-background"
            >
                <QuillQueryToolbar codeEditorKey={codeEditorKey} inspectorDocked={docked} />
                <div className="relative min-h-0 flex-1">
                    <ResizablePanelGroup
                        key={`${layout.inspector.side}-${docked}`}
                        orientation="horizontal"
                        defaultLayout={workspaceSizes ?? undefined}
                        onLayoutChanged={setWorkspaceSizes}
                    >
                        {inspectorOnLeft && inspectorPanel ? (
                            <>
                                {inspectorPanel}
                                <ResizableHandle />
                            </>
                        ) : null}
                        <ResizablePanel id="workspace" minSize="20rem">
                            {queryAndResults}
                        </ResizablePanel>
                        {!inspectorOnLeft && inspectorPanel ? (
                            <>
                                <ResizableHandle />
                                {inspectorPanel}
                            </>
                        ) : null}
                    </ResizablePanelGroup>
                    {inspectorOverlayOpen && !docked ? (
                        <>
                            <button
                                type="button"
                                aria-label="Close side panel"
                                className="absolute inset-0 z-10 cursor-default bg-foreground/10"
                                onClick={() => setInspectorOverlayOpen(false)}
                            />
                            <div
                                className={
                                    inspectorOnLeft
                                        ? 'absolute inset-y-0 left-0 z-20 w-80 max-w-full border-r bg-background shadow-lg'
                                        : 'absolute inset-y-0 right-0 z-20 w-80 max-w-full border-l bg-background shadow-lg'
                                }
                            >
                                <QuillSqlEditorInspector tabId={tabId} floating />
                            </div>
                        </>
                    ) : null}
                </div>
                <NewVariableModal />
                <VimrcModal editorKey={codeEditorKey} />
            </div>
        </QuillSurfaceContext.Provider>
    )
}
