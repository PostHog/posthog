import { useActions, useValues } from 'kea'

import { IconBolt, IconSidePanel } from '@posthog/icons'
import { Button, Separator } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { viewEngine } from 'products/data_warehouse/frontend/shared/viewEngine'

import { QuillFixErrorButton } from './QuillFixErrorButton'
import { QuillQueryFiltersPopover } from './QuillQueryFiltersPopover'
import { QuillRunButton } from './QuillRunButton'
import { QuillWorkspaceMoreMenu } from './QuillWorkspaceMoreMenu'
import { sqlEditorLayoutLogic } from './sqlEditorLayoutLogic'

/**
 * The query toolbar: Run, the scene's only primary action, then filters, then what only shows when
 * it applies (materialization while editing a view, Fix with AI while there is an error). The rest
 * sits in "More". The side panel toggle sits on the panel's own side.
 */
export function QuillQueryToolbar({
    codeEditorKey,
    inspectorDocked,
}: {
    codeEditorKey: string
    /** False when the side panel floats over the query, because the workspace is too narrow to dock it. */
    inspectorDocked: boolean
}): JSX.Element {
    const { editingView, singleStatementDisabledReason } = useValues(sqlEditorLogic)
    const { openMaterializationModal } = useActions(sqlEditorLogic)
    const { layout, inspectorOverlayOpen } = useValues(sqlEditorLayoutLogic)
    const { toggleInspector, setInspectorOverlayOpen } = useActions(sqlEditorLayoutLogic)
    const panelOpen = inspectorDocked ? layout.inspector.open : inspectorOverlayOpen

    const panelToggle = (
        <Button
            size="icon"
            onClick={() => (inspectorDocked ? toggleInspector() : setInspectorOverlayOpen(!inspectorOverlayOpen))}
            aria-pressed={panelOpen}
            aria-label={panelOpen ? 'Hide side panel' : 'Show side panel'}
            tooltip={panelOpen ? 'Hide side panel' : 'Show side panel'}
            data-attr="sql-editor-inspector-toggle"
        >
            <IconSidePanel className={layout.inspector.side === 'left' ? '-scale-x-100' : undefined} />
        </Button>
    )

    return (
        <div className="flex min-h-11 shrink-0 flex-wrap items-center gap-1.5 border-b px-2 py-1.5">
            {layout.inspector.side === 'left' ? panelToggle : null}
            <QuillRunButton runQueryDisabledReason={singleStatementDisabledReason ?? undefined} />
            <Separator orientation="vertical" className="mx-1 h-4" />
            <QuillQueryFiltersPopover />
            {editingView ? (
                <AccessControlAction
                    resourceType={AccessControlResourceType.WarehouseObjects}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <Button
                        variant="outline"
                        onClick={() => openMaterializationModal(editingView)}
                        disabledReason={viewEngine(editingView).capabilities.materialize.reason ?? undefined}
                        data-attr="sql-editor-materialization-button"
                    >
                        <IconBolt />
                        <span className="@max-[44rem]/sql-workspace:hidden">Materialization…</span>
                    </Button>
                </AccessControlAction>
            ) : null}
            <div className="ms-auto flex items-center gap-1.5">
                <QuillFixErrorButton source="action-bar" hideWithoutError />
                <QuillWorkspaceMoreMenu codeEditorKey={codeEditorKey} />
                {layout.inspector.side === 'right' ? panelToggle : null}
            </div>
        </div>
    )
}
