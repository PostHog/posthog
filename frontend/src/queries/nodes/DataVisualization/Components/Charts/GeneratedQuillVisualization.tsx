import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput } from '@posthog/lemon-ui'

import { ChartSpecRenderer } from 'lib/components/ChartSpecRenderer/ChartSpecRenderer'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'

import type { HogQLQueryResponse } from '~/queries/schema/schema-general'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { generatedQuillChartLogic } from './generatedQuillChartLogic'

export function GeneratedQuillVisualization(): JSX.Element {
    const { response, query, currentTeamId, dataVisualizationProps } = useValues(dataVisualizationLogic)
    const logic = generatedQuillChartLogic({ key: dataVisualizationProps.key })
    const { prompt, chartSpec, warnings, generationLoading } = useValues(logic)
    const { setPrompt, generateChart } = useActions(logic)

    const hogqlResponse = response as HogQLQueryResponse | null
    const columns: string[] = hogqlResponse?.columns ?? []
    const rows = (hogqlResponse?.results as unknown[][] | undefined) ?? []
    const columnTypes = hogqlResponse?.types as (string | null)[] | undefined
    const canGenerate = columns.length > 0 && rows.length > 0 && !!currentTeamId

    const onGenerate = (): void => {
        if (!currentTeamId) {
            return
        }
        generateChart({
            teamId: currentTeamId,
            query: (query.source as { query?: string }).query ?? '',
            columns,
            columnTypes,
            rows,
        })
    }

    return (
        <div className="flex flex-col gap-3 p-3 h-full">
            <div className="flex gap-2 items-center">
                <LemonInput
                    className="flex-1"
                    value={prompt}
                    onChange={setPrompt}
                    onPressEnter={onGenerate}
                    placeholder="Describe the chart you want (optional)…"
                    disabled={generationLoading}
                />
                <LemonButton
                    type="primary"
                    icon={<IconSparkles />}
                    onClick={onGenerate}
                    loading={generationLoading}
                    disabledReason={!canGenerate ? 'Run a query first' : undefined}
                >
                    {chartSpec ? 'Regenerate' : 'Generate'}
                </LemonButton>
            </div>

            {warnings.map((warning, i) => (
                <LemonBanner key={i} type="warning">
                    {warning}
                </LemonBanner>
            ))}

            <div className="flex-1 min-h-0">
                {generationLoading ? (
                    <div className="flex items-center justify-center h-full">
                        <LoadingBar />
                    </div>
                ) : chartSpec ? (
                    <ChartSpecRenderer spec={chartSpec} className="h-full" height={360} />
                ) : (
                    <div className="flex items-center justify-center h-full text-secondary">
                        Generate an on-brand chart from your query results.
                    </div>
                )}
            </div>
        </div>
    )
}
