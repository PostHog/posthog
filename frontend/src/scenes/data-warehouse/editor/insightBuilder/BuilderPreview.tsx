import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
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

/** The chart itself — the always-visible Visualization column of the builder canvas. */
export function BuilderPreview({ tabId }: { tabId: string }): JSX.Element {
    const { hasAnyField, wellProblems, builderDisplay } = useValues(insightBuilderLogic({ tabId }))
    const { sourceQuery, dataLogicKey } = useValues(sqlEditorLogic({ tabId }))
    const { setSourceQuery } = useActions(sqlEditorLogic({ tabId }))
    const { response, responseError, hasMoreData } = useValues(dataNodeLogic)

    const capability = getChartCapability(builderDisplay)
    // Some backends embed the failure in the response body rather than the error channel
    const queryError =
        responseError ??
        (response && typeof response === 'object' && 'error' in response
            ? (response as { error?: string }).error
            : null)

    if (!hasAnyField) {
        return (
            <PreviewEmptyState
                heading="Build an insight from your query"
                details={['Drag fields from the Data column into Rows and Values, or click a field to add it.']}
            />
        )
    }
    if (wellProblems.length > 0) {
        return (
            <PreviewEmptyState
                heading={`${capability?.label ?? 'This chart'} needs more fields`}
                details={wellProblems}
            />
        )
    }
    if (queryError) {
        return (
            <div className="flex flex-col gap-2 p-4">
                <LemonBanner type="error">{queryError}</LemonBanner>
                <span className="text-sm text-secondary">
                    If a field no longer exists in the query, remove its highlighted pill or refresh the fields in the
                    Data column.
                </span>
            </div>
        )
    }
    return (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-auto">
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
