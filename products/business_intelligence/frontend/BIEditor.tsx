import { BindLogic, useActions, useValues } from 'kea'
import { useRef, type ReactNode, type Ref } from 'react'

import { IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic, ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { IconTableChart } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { BICalculatedMeasureModal } from 'products/business_intelligence/frontend/BICalculatedMeasureModal'
import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import {
    BI_SHELF_PILL_DRAG_MIME_TYPE,
    parseBIShelfPillDragData,
} from 'products/business_intelligence/frontend/biEditorTypes'
import { BIChartTypes } from 'products/business_intelligence/frontend/components/BIChartTypes'
import { BIDataPane } from 'products/business_intelligence/frontend/components/BIDataPane'
import { BIFieldPill } from 'products/business_intelligence/frontend/components/BIFieldPill'
import { BIFiltersCard } from 'products/business_intelligence/frontend/components/BIFiltersCard'
import { BIMarksCard } from 'products/business_intelligence/frontend/components/BIMarksCard'
import { BIShelfStrip } from 'products/business_intelligence/frontend/components/BIShelfStrip'
import { BIToolbar } from 'products/business_intelligence/frontend/components/BIToolbar'

import { BIAnalysisControls } from './BIAnalysisControls'
import { BILocalFieldModal } from './BILocalFieldModal'
import { BIMeasureSettingsModal } from './BIMeasureSettingsModal'

export function BIEditor({
    tabId,
    children,
    settingsPanelRef,
}: {
    tabId: string
    children: ReactNode
    settingsPanelRef: Ref<HTMLDivElement>
}): JSX.Element {
    const { config, activePanel, fieldsPaneOpen, dragSessionId } = useValues(biEditorLogic({ tabId }))
    const { removeFieldFromShelf, setActiveDropShelf, setActivePanel, toggleFieldsPane } = useActions(
        biEditorLogic({ tabId })
    )
    const containerRef = useRef<HTMLDivElement>(null)
    const biEditorResizerProps: ResizerLogicProps = {
        logicKey: 'bi-editor-side-pane',
        placement: 'right',
        containerRef,
        persistent: true,
    }
    const { desiredSize } = useValues(resizerLogic(biEditorResizerProps))
    const biSidePaneWidth = Math.min(400, Math.max(180, desiredSize ?? 240))

    const contextPanel = activePanel && (!config.querySnapshot || activePanel === 'display') && (
        <aside
            className="absolute inset-y-0 right-0 z-10 flex w-72 max-w-full flex-col border-l bg-surface-primary shadow-md @5xl/bi-editor:static @5xl/bi-editor:max-w-[25%] @5xl/bi-editor:shrink-0 @5xl/bi-editor:shadow-none"
            aria-label={
                activePanel === 'charts' ? 'Charts' : activePanel === 'analysis' ? 'Analysis' : 'Chart settings'
            }
            data-attr="bi-editor-context-panel"
        >
            <div className="flex items-center justify-between border-b px-2 py-1">
                <span className="text-sm font-semibold">
                    {activePanel === 'charts' ? 'Charts' : activePanel === 'analysis' ? 'Analysis' : 'Chart settings'}
                </span>
                <LemonButton
                    icon={<IconX />}
                    size="xsmall"
                    type="tertiary"
                    aria-label="Close panel"
                    onClick={() => setActivePanel(null)}
                    data-attr="bi-editor-close-panel"
                />
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto" ref={settingsPanelRef}>
                {activePanel === 'charts' && (
                    <>
                        <BIChartTypes />
                        <BIMarksCard />
                    </>
                )}
                {activePanel === 'analysis' && <BIAnalysisControls />}
            </div>
        </aside>
    )

    if (config.querySnapshot) {
        return (
            <BindLogic logic={biEditorLogic} props={{ tabId }}>
                <div className="@container/bi-editor flex min-h-0 flex-1 flex-col" data-attr="bi-catalog-snapshot">
                    <LemonBanner type="info" dismissKey="bi-query-snapshot">
                        This is a fixed SQL copy. Use View SQL to edit its dates or grouping in the SQL editor. Catalog
                        changes won't update this copy.{' '}
                        {config.catalogMetric && (
                            <Link to={urls.dataCatalogMetric(config.catalogMetric)}>View catalog definition</Link>
                        )}
                    </LemonBanner>
                    <BIToolbar />
                    <div className="relative flex min-h-0 flex-1">
                        <div className="flex min-h-0 min-w-0 flex-1 flex-col">{children}</div>
                        {contextPanel}
                    </div>
                </div>
            </BindLogic>
        )
    }

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
                    if (pill?.dragSessionId === dragSessionId && !event.altKey) {
                        event.preventDefault()
                        removeFieldFromShelf(pill.shelf, pill.index)
                    }
                    setActiveDropShelf(null)
                }}
                onDragEnd={() => setActiveDropShelf(null)}
            >
                <BIToolbar />
                <BICalculatedMeasureModal />
                <BILocalFieldModal />
                <BIMeasureSettingsModal />
                <div className="relative flex min-h-0 flex-1">
                    {fieldsPaneOpen && (
                        <div
                            ref={containerRef}
                            className="relative flex min-h-0 w-[var(--bi-side-pane-width)] max-w-[40%] shrink-0 flex-col border-r @5xl/bi-editor:max-w-[25%]"
                            style={{ '--bi-side-pane-width': `${biSidePaneWidth}px` } as React.CSSProperties}
                            data-attr="bi-editor-fields-pane"
                        >
                            <div className="flex items-center justify-between px-2 pt-1">
                                <span className="text-sm font-semibold">Fields</span>
                                <LemonButton
                                    icon={<IconX />}
                                    size="xsmall"
                                    type="tertiary"
                                    aria-label="Hide fields panel"
                                    onClick={toggleFieldsPane}
                                    data-attr="bi-editor-close-fields"
                                />
                            </div>
                            <BIDataPane tabId={tabId} />
                            <Resizer {...biEditorResizerProps} />
                        </div>
                    )}
                    <div className="flex min-w-0 flex-1 flex-col" data-attr="bi-editor-canvas">
                        <BIShelfStrip
                            shelf="columns"
                            title="Columns"
                            icon={<IconTableChart className="rotate-90" />}
                            emptyText="Drop dimensions here for a second grouping"
                        >
                            {[
                                ...config.columns.map((field, index) => (
                                    <BIFieldPill key={field.id} shelf="columns" index={index} />
                                )),
                                ...config.values.flatMap((value, index) =>
                                    value.shelf === 'columns'
                                        ? [
                                              <BIFieldPill
                                                  key={`${value.field.id}-${index}`}
                                                  shelf="values"
                                                  index={index}
                                              />,
                                          ]
                                        : []
                                ),
                            ]}
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
                                ...config.values.flatMap((value, index) =>
                                    value.shelf !== 'columns'
                                        ? [
                                              <BIFieldPill
                                                  key={`${value.field.id}-${index}`}
                                                  shelf="values"
                                                  index={index}
                                              />,
                                          ]
                                        : []
                                ),
                                ...(config.values.length === 0 && (config.rows.length > 0 || config.columns.length > 0)
                                    ? [
                                          <LemonTag
                                              key="count"
                                              type="success"
                                              title="Counts source rows in each group. Add a measure to replace this count."
                                          >
                                              Count of rows
                                          </LemonTag>,
                                      ]
                                    : []),
                            ]}
                        </BIShelfStrip>
                        <BIFiltersCard />
                        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
                    </div>
                    {contextPanel}
                </div>
            </div>
        </BindLogic>
    )
}
