import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { FlintQuillChart, quillTemplateDefs } from 'lib/charts/flint'

import type { HogQLQueryResponse } from '~/queries/schema/schema-general'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { flintChartInput } from './flintChartInput'
import { flintQuillVisualizationLogic } from './flintQuillVisualizationLogic'

const CHART_TYPE_OPTIONS = [
    { value: null, label: 'Auto' },
    ...quillTemplateDefs.map((t) => ({ value: t.chart as string | null, label: t.chart })),
]

export interface FlintQuillVisualizationProps {
    /** Fixed 60vh chart height for the SQL editor pane, whose flex layout gives children no definite height. */
    presetChartHeight?: boolean
}

/** SQL editor output-pane view: renders the query results through the flint-chart quill backend.
 *  A spec is inferred from the result shape immediately; an optional prompt asks the model for a
 *  better one (the model only maps columns to channels — rows never leave the client). */
export function FlintQuillVisualization({ presetChartHeight }: FlintQuillVisualizationProps): JSX.Element {
    const { response, dataVisualizationProps, query, currentTeamId } = useValues(dataVisualizationLogic)
    const logic = flintQuillVisualizationLogic({ key: dataVisualizationProps.key })
    const { chartType, prompt, generatedInput, generationLoading, narrative, warnings } = useValues(logic)
    const { setChartType, setPrompt, generateSpec } = useActions(logic)

    const hogqlResponse = response as HogQLQueryResponse | null
    const { columns, columnTypes, rows } = useMemo(() => {
        const columns: string[] = hogqlResponse?.columns ?? []
        const rows = (hogqlResponse?.results as unknown[][] | undefined) ?? []
        // HogQL `types` entries are `[columnName, clickhouseType]` tuples — pull out the type string
        const columnTypes: (string | null)[] = ((hogqlResponse?.types as unknown[][] | undefined) ?? []).map((t) =>
            Array.isArray(t) ? ((t[1] as string | undefined) ?? null) : null
        )
        return { columns, columnTypes, rows }
    }, [hogqlResponse])

    const input = useMemo(() => {
        if (generatedInput) {
            // A manual chart-type pick re-targets the generated spec's encodings
            return chartType
                ? { ...generatedInput, chart_spec: { ...generatedInput.chart_spec, chartType } }
                : generatedInput
        }
        return flintChartInput({ columns, columnTypes, rows, chartType })
    }, [generatedInput, columns, columnTypes, rows, chartType])

    const onGenerate = (): void => {
        if (!currentTeamId) {
            return
        }
        generateSpec({
            teamId: currentTeamId,
            query: (query.source as { query?: string }).query ?? '',
            columns,
            columnTypes,
            rows,
        })
    }

    if (!input) {
        return (
            <div className="flex items-center justify-center h-full text-secondary">
                Run a query to render its results as a Flint chart.
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2 p-3 h-full">
            <div className="flex items-center gap-2">
                <LemonSelect
                    size="small"
                    value={chartType}
                    onChange={setChartType}
                    options={CHART_TYPE_OPTIONS}
                    data-attr="flint-chart-type"
                />
                <LemonInput
                    className="flex-1"
                    size="small"
                    value={prompt}
                    onChange={setPrompt}
                    onPressEnter={onGenerate}
                    placeholder="Describe the chart you want (optional)…"
                    disabled={generationLoading}
                />
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconSparkles />}
                    onClick={onGenerate}
                    loading={generationLoading}
                    disabledReason={
                        columns.length === 0 || rows.length === 0
                            ? 'Run a query first'
                            : !currentTeamId
                              ? 'No team'
                              : undefined
                    }
                >
                    {generatedInput ? 'Regenerate' : 'Generate'}
                </LemonButton>
            </div>

            {warnings.map((warning, i) => (
                <LemonBanner key={i} type="warning">
                    {warning}
                </LemonBanner>
            ))}

            <div
                className={clsx(
                    // `flex flex-col` is load-bearing: quill chart roots size themselves with
                    // `flex-1`, which only engages inside a flex container — without it the
                    // canvas collapses to 0px height (same pattern as SqlLineGraph)
                    'rounded bg-surface-primary p-2 flex flex-col',
                    presetChartHeight ? 'h-[60vh]' : 'flex-1 min-h-0'
                )}
            >
                <FlintQuillChart input={input} className="h-full" dataAttr="flint-quill-visualization" />
            </div>

            {narrative && <div className="text-xs text-secondary">{narrative}</div>}
        </div>
    )
}
