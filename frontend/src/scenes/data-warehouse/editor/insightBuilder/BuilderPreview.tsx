import { useActions, useValues } from 'kea'

import { IconPalette, IconX } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { SideBar } from '~/queries/nodes/DataVisualization/Components/SideBar'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { getChartCapability } from '~/queries/nodes/DataVisualization/insightBuilder/chartCapabilities'

import { InternalDataTableVisualization } from '../OutputPane'
import { sqlEditorLogic } from '../sqlEditorLogic'
import { insightBuilderLogic } from './insightBuilderLogic'

function PreviewEmptyState({ heading, details }: { heading: string; details: string[] }): JSX.Element {
    return (
        <div
            className="flex flex-1 flex-col items-center justify-center gap-2 p-4 text-center"
            data-attr="sql-builder-preview-empty-state"
        >
            <span className="text-base font-semibold">{heading}</span>
            {details.map((detail) => (
                <span key={detail} className="text-sm text-secondary">
                    {detail}
                </span>
            ))}
        </div>
    )
}

export function BuilderPreview({ tabId }: { tabId: string }): JSX.Element {
    const { hasAnyField, wellProblems, builderDisplay } = useValues(insightBuilderLogic({ tabId }))
    const { sourceQuery, dataLogicKey } = useValues(sqlEditorLogic({ tabId }))
    const { setSourceQuery } = useActions(sqlEditorLogic({ tabId }))
    const { isChartSettingsPanelOpen } = useValues(dataVisualizationLogic)
    const { toggleChartSettingsPanel } = useActions(dataVisualizationLogic)
    const { responseError, hasMoreData } = useValues(dataNodeLogic)

    const capability = getChartCapability(builderDisplay)

    let content: JSX.Element
    if (!hasAnyField) {
        content = (
            <PreviewEmptyState
                heading="Build an insight from your query"
                details={['Drag fields from the left into Rows and Values, or click a field to add it.']}
            />
        )
    } else if (wellProblems.length > 0) {
        content = (
            <PreviewEmptyState
                heading={`${capability?.label ?? 'This chart'} needs more fields`}
                details={wellProblems}
            />
        )
    } else if (responseError) {
        content = (
            <div className="p-4">
                <LemonBanner type="error">{responseError}</LemonBanner>
            </div>
        )
    } else {
        content = (
            <div className="flex min-h-0 flex-1 flex-col overflow-auto">
                {hasMoreData ? (
                    <LemonBanner type="info" className="m-2 flex-shrink-0">
                        Results were truncated at the row limit — aggregates may be incomplete. Narrow the base query or
                        reduce the grouping cardinality.
                    </LemonBanner>
                ) : null}
                <InternalDataTableVisualization
                    uniqueKey={dataLogicKey}
                    query={sourceQuery}
                    setQuery={setSourceQuery}
                    context={{}}
                    cachedResults={undefined}
                    editMode
                    showSettingsPanel={false}
                />
            </div>
        )
    }

    return (
        // min-w-0 keeps wide results from growing this flex item past the viewport, which would
        // push the Format drawer off-screen
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="flex items-center justify-between border-b px-2 py-1">
                <span className="text-xs font-semibold uppercase text-tertiary">Preview</span>
                <LemonButton
                    icon={<IconPalette />}
                    size="small"
                    type="tertiary"
                    active={isChartSettingsPanelOpen}
                    onClick={() => toggleChartSettingsPanel()}
                    tooltip="Format"
                    data-attr="sql-builder-format-toggle"
                />
            </div>
            <div className="flex min-h-0 flex-1">
                <div className="flex min-w-0 flex-1 flex-col">{content}</div>
                {isChartSettingsPanelOpen ? (
                    <div className="flex w-72 shrink-0 flex-col overflow-hidden border-l">
                        <div className="flex shrink-0 items-center justify-between border-b px-2 py-1">
                            <span className="text-xs font-semibold uppercase text-tertiary">Format</span>
                            <LemonButton
                                icon={<IconX />}
                                size="xsmall"
                                type="tertiary"
                                onClick={() => toggleChartSettingsPanel(false)}
                                tooltip="Close"
                                data-attr="sql-builder-format-close"
                            />
                        </div>
                        <div className="min-h-0 flex-1 overflow-y-auto">
                            <SideBar />
                        </div>
                    </div>
                ) : null}
            </div>
        </div>
    )
}
