import { BindLogic, useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { IconTableChart } from 'lib/lemon-ui/icons'

import { BICalculatedMeasureModal } from 'products/data_warehouse/frontend/bi/BICalculatedMeasureModal'

import { editorSizingLogic } from '../editorSizingLogic'
import { biEditorLogic } from './biEditorLogic'
import { BI_SHELF_PILL_DRAG_MIME_TYPE, parseBIShelfPillDragData } from './biEditorTypes'
import { BIDataPane } from './components/BIDataPane'
import { BIFieldPill } from './components/BIFieldPill'
import { BIFiltersCard } from './components/BIFiltersCard'
import { BIMarksCard } from './components/BIMarksCard'
import { BIShelfStrip } from './components/BIShelfStrip'
import { BIShowMe } from './components/BIShowMe'
import { BIToolbar } from './components/BIToolbar'

/**
 * A worksheet laid out like desktop BI tools: data pane, filter and marks cards, rows and columns
 * shelves above the view, and a chart picker on the right.
 */
export function BIEditor({ tabId, children }: { tabId: string; children: ReactNode }): JSX.Element {
    const { config, showMeOpen, dragSessionId } = useValues(biEditorLogic({ tabId }))
    const { removeFieldFromShelf, setActiveDropShelf } = useActions(biEditorLogic({ tabId }))
    const { biSidePaneWidth, biEditorResizerProps } = useValues(editorSizingLogic)

    return (
        <BindLogic logic={biEditorLogic} props={{ tabId }}>
            <div
                className="@container/bi-editor flex min-h-0 flex-1 flex-col overflow-hidden bg-primary"
                onDragOver={(event) => {
                    if (event.dataTransfer.types.includes(BI_SHELF_PILL_DRAG_MIME_TYPE)) {
                        event.preventDefault()
                    }
                }}
                onDrop={(event) => {
                    const pill = parseBIShelfPillDragData(event.dataTransfer.getData(BI_SHELF_PILL_DRAG_MIME_TYPE))
                    if (pill?.dragSessionId === dragSessionId) {
                        event.preventDefault()
                        removeFieldFromShelf(pill.shelf, pill.index)
                    }
                    setActiveDropShelf(null)
                }}
                onDragEnd={() => setActiveDropShelf(null)}
            >
                <BIToolbar />
                <BICalculatedMeasureModal />
                <div className="flex min-h-0 flex-1">
                    <div
                        className="relative flex w-[var(--bi-side-pane-width)] shrink-0 flex-col border-r @4xl/bi-editor:w-[calc(var(--bi-side-pane-width)+12rem)] @4xl/bi-editor:flex-row"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ '--bi-side-pane-width': `${biSidePaneWidth}px` } as React.CSSProperties}
                    >
                        {/* The resizer measures the data pane alone, because the cards column has a fixed width */}
                        <div ref={biEditorResizerProps.containerRef} className="flex min-h-0 min-w-0 flex-1 flex-col">
                            <BIDataPane />
                        </div>
                        <div className="flex max-h-[50%] shrink-0 flex-col overflow-y-auto border-t @4xl/bi-editor:max-h-none @4xl/bi-editor:w-48 @4xl/bi-editor:border-l @4xl/bi-editor:border-t-0">
                            <BIFiltersCard />
                            <BIMarksCard />
                        </div>
                        <Resizer {...biEditorResizerProps} />
                    </div>
                    <div className="flex min-w-0 flex-1 flex-col">
                        <BIShelfStrip
                            shelf="columns"
                            title="Columns"
                            icon={<IconTableChart className="rotate-90" />}
                            emptyText="Drop dimensions here for a second grouping"
                        >
                            {config.columns.map((field, index) => (
                                <BIFieldPill key={field.id} shelf="columns" index={index} />
                            ))}
                        </BIShelfStrip>
                        <BIShelfStrip
                            shelf="rows"
                            title="Rows"
                            icon={<IconTableChart />}
                            emptyText="Drop dimensions or measures here"
                        >
                            {[
                                ...config.rows.map((field, index) => (
                                    <BIFieldPill key={field.id} shelf="rows" index={index} />
                                )),
                                ...config.values.map((value, index) => (
                                    <BIFieldPill key={`${value.field.id}-${index}`} shelf="values" index={index} />
                                )),
                            ]}
                        </BIShelfStrip>
                        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
                    </div>
                    {showMeOpen ? (
                        <div className="hidden shrink-0 border-l bg-surface-primary @3xl/bi-editor:flex">
                            <BIShowMe docked />
                        </div>
                    ) : null}
                </div>
            </div>
        </BindLogic>
    )
}
