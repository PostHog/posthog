import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { JSONViewer } from 'lib/components/JSONViewer'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'

import { DataVisualizationNode, HogQLQueryResponse } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { GENERATED_VEGA_LITE_VIEW_ATTR } from '../../generatedVegaLiteUtils'
import { Table } from '../Table'
import { VegaLiteChart } from './VegaLiteChart'

interface GeneratedVegaLiteVisualizationProps {
    uniqueKey?: string | number
    query: DataVisualizationNode
    context?: QueryContext<DataVisualizationNode>
    cachedResults?: HogQLQueryResponse
    embedded?: boolean
}

export const GeneratedVegaLiteVisualization = ({
    uniqueKey,
    query,
    context,
    cachedResults,
    embedded,
}: GeneratedVegaLiteVisualizationProps): JSX.Element => {
    const { chartSettings, columns, generatedVegaLiteResponseLoading, response } = useValues(dataVisualizationLogic)
    const { generateVegaLiteChart, updateChartSettings } = useActions(dataVisualizationLogic)
    const generatedSettings = chartSettings.generatedVegaLite
    const hasColumns = !!response && columns.length > 0
    const [localRenderError, setLocalRenderError] = useState<string | null>(null)

    useEffect(() => {
        setLocalRenderError(null)
    }, [generatedSettings?.validatedSpec])

    const handleRenderError = useCallback(
        (renderError: string) => {
            setLocalRenderError(renderError)
            updateChartSettings({
                generatedVegaLite: {
                    renderError,
                },
            })
        },
        [updateChartSettings]
    )

    const tableFallback = (
        <div className="min-h-64 flex-1 overflow-auto">
            <Table
                uniqueKey={uniqueKey}
                query={query}
                context={context}
                cachedResults={cachedResults}
                embedded={embedded}
            />
        </div>
    )

    if (!hasColumns) {
        return (
            <div className="flex flex-col gap-3 p-3 h-full" data-attr={GENERATED_VEGA_LITE_VIEW_ATTR}>
                <LemonBanner type="info">Run a query before generating a visualization.</LemonBanner>
                {tableFallback}
            </div>
        )
    }

    const renderError = localRenderError || generatedSettings?.renderError

    if (generatedVegaLiteResponseLoading && (!generatedSettings?.validatedSpec || renderError)) {
        return (
            <div
                className="flex flex-col flex-1 justify-center items-center bg-surface-primary h-full"
                data-attr={GENERATED_VEGA_LITE_VIEW_ATTR}
            >
                <LoadingBar />
            </div>
        )
    }

    if (generatedSettings?.validationError) {
        return (
            <div className="flex flex-col gap-3 p-3 h-full" data-attr={GENERATED_VEGA_LITE_VIEW_ATTR}>
                <LemonBanner type="warning">Validation failed: {generatedSettings.validationError}</LemonBanner>
                {generatedSettings.spec ? (
                    <div className="border rounded bg-surface-primary p-2 overflow-auto max-h-80">
                        <JSONViewer src={generatedSettings.spec as object} name={null} collapsed={1} sortKeys />
                    </div>
                ) : null}
                {tableFallback}
            </div>
        )
    }

    if (renderError) {
        return (
            <div className="flex flex-col gap-3 p-3 h-full" data-attr={GENERATED_VEGA_LITE_VIEW_ATTR}>
                <LemonBanner type="warning">Render failed: {renderError}</LemonBanner>
                {tableFallback}
            </div>
        )
    }

    if (generatedSettings?.validatedSpec && generatedSettings.fields && response) {
        return (
            <VegaLiteChart
                response={response as HogQLQueryResponse}
                spec={generatedSettings.validatedSpec}
                fields={generatedSettings.fields}
                onRenderError={handleRenderError}
            />
        )
    }

    return (
        <div
            className="flex flex-col gap-3 items-center justify-center h-full p-3 bg-surface-primary"
            data-attr={GENERATED_VEGA_LITE_VIEW_ATTR}
        >
            <div className="text-secondary">Generate a chart from these SQL results.</div>
            <LemonButton
                type="primary"
                icon={<IconSparkles />}
                onClick={() => generateVegaLiteChart()}
                loading={generatedVegaLiteResponseLoading}
            >
                Generate
            </LemonButton>
        </div>
    )
}
