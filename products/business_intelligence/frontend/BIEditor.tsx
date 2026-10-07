import { BindLogic, useActions, useValues } from 'kea'
import { useRef, type ReactNode } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic, ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { IconTableChart } from 'lib/lemon-ui/icons'

import { BICalculatedMeasureModal } from 'products/business_intelligence/frontend/BICalculatedMeasureModal'
import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import {
    BI_SHELF_PILL_DRAG_MIME_TYPE,
    parseBIShelfPillDragData,
} from 'products/business_intelligence/frontend/biEditorTypes'
import { BIFilterControl } from 'products/business_intelligence/frontend/BIFilterControl'
import { BIDataPane } from 'products/business_intelligence/frontend/components/BIDataPane'
import { BIFieldPill } from 'products/business_intelligence/frontend/components/BIFieldPill'
import { BIFiltersCard } from 'products/business_intelligence/frontend/components/BIFiltersCard'
import { BIMarksCard } from 'products/business_intelligence/frontend/components/BIMarksCard'
import { BIShelfStrip } from 'products/business_intelligence/frontend/components/BIShelfStrip'
import { BIShowMe } from 'products/business_intelligence/frontend/components/BIShowMe'
import { BIToolbar } from 'products/business_intelligence/frontend/components/BIToolbar'

import { BIAnalysisControls } from './BIAnalysisControls'
import { BIMeasureSettingsModal } from './BIMeasureSettingsModal'
import { BIResultFiltersCard } from './components/BIResultFiltersCard'

/**
 * A worksheet laid out like desktop BI tools: data pane, filter and marks cards, rows and columns
 * shelves above the view, and a chart picker on the right.
 */
export function BIEditor({ tabId, children }: { tabId: string; children: ReactNode }): JSX.Element {
    const { config, showMeOpen, dragSessionId } = useValues(biEditorLogic({ tabId }))
    const { removeFieldFromShelf, setActiveDropShelf } = useActions(biEditorLogic({ tabId }))
    const containerRef = useRef<HTMLDivElement>(null)
    const cardsRef = useRef<HTMLDivElement>(null)
    const biEditorResizerProps: ResizerLogicProps = {
        logicKey: 'bi-editor-side-pane',
        placement: 'right',
        containerRef,
        persistent: true,
    }
    const { desiredSize } = useValues(resizerLogic(biEditorResizerProps))
    const biSidePaneWidth = Math.min(400, Math.max(180, desiredSize ?? 240))
    const cardsResizerProps: ResizerLogicProps = {
        logicKey: 'bi-editor-cards-pane',
        placement: 'right',
        containerRef: cardsRef,
        persistent: true,
    }
    const { desiredSize: cardsDesiredSize } = useValues(resizerLogic(cardsResizerProps))
    const cardsWidth = Math.min(320, Math.max(160, cardsDesiredSize ?? 160))

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
                <BIMeasureSettingsModal />
                <div className="flex min-h-0 flex-1">
                    <div
                        className="relative flex w-[var(--bi-side-pane-width)] max-w-[50%] shrink-0 flex-col border-r @5xl/bi-editor:w-[calc(var(--bi-side-pane-width)+var(--bi-cards-width))] @5xl/bi-editor:max-w-none @5xl/bi-editor:flex-row"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={
                            {
                                '--bi-side-pane-width': `${biSidePaneWidth}px`,
                                '--bi-cards-width': `${cardsWidth}px`,
                            } as React.CSSProperties
                        }
                    >
                        <div ref={containerRef} className="relative flex min-h-0 min-w-0 flex-1 flex-col">
                            <BIDataPane tabId={tabId} />
                            <Resizer {...biEditorResizerProps} />
                        </div>
                        <div
                            ref={cardsRef}
                            className="relative flex min-h-0 max-h-[40%] shrink-0 flex-col border-t @5xl/bi-editor:max-h-none @5xl/bi-editor:w-[var(--bi-cards-width)] @5xl/bi-editor:border-l @5xl/bi-editor:border-t-0"
                        >
                            <div className="min-h-0 overflow-y-auto">
                                <BIFiltersCard />
                                <BIResultFiltersCard />
                                <BIMarksCard />
                                <BIAnalysisControls />
                            </div>
                            <Resizer {...cardsResizerProps} className="hidden @5xl/bi-editor:block" />
                        </div>
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
                    {showMeOpen || config.filters.length > 0 ? (
                        <div className="hidden w-44 shrink-0 flex-col overflow-y-auto border-l bg-surface-primary @3xl/bi-editor:flex @6xl/bi-editor:w-80">
                            {config.filters.length > 0 && (
                                <section className="border-b p-2" aria-label="Quick filters">
                                    <h3 className="mb-2 text-xs font-semibold">Row filters</h3>
                                    <div className="grid grid-cols-1 items-start gap-x-2 gap-y-2 @6xl/bi-editor:grid-cols-2">
                                        {config.filters.map((filter, index) => (
                                            <BIFilterControl key={filter.field.id} index={index} />
                                        ))}
                                    </div>
                                </section>
                            )}
                            {showMeOpen && <BIShowMe docked />}
                        </div>
                    ) : null}
                </div>
            </div>
        </BindLogic>
    )
}
