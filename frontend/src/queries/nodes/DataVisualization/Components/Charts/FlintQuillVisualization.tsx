import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { FlintQuillChart, quillTemplateDefs } from 'lib/charts/flint'

import type { HogQLQueryResponse } from '~/queries/schema/schema-general'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { flintChartInput } from './flintChartInput'
import { flintQuillVisualizationLogic } from './flintQuillVisualizationLogic'

const CHART_TYPE_OPTIONS = [
    { value: null, label: 'Auto' },
    ...quillTemplateDefs.map((t) => ({ value: t.chart as string | null, label: t.chart })),
]

/** SQL editor output-pane view: renders the query results through the
 *  flint-chart quill backend, inferring a spec from the result shape. */
export function FlintQuillVisualization(): JSX.Element {
    const { response, dataVisualizationProps } = useValues(dataVisualizationLogic)
    const logic = flintQuillVisualizationLogic({ key: dataVisualizationProps.key })
    const { chartType } = useValues(logic)
    const { setChartType } = useActions(logic)

    const hogqlResponse = response as HogQLQueryResponse | null
    const input = useMemo(() => {
        const columns: string[] = hogqlResponse?.columns ?? []
        const rows = (hogqlResponse?.results as unknown[][] | undefined) ?? []
        // HogQL `types` entries are `[columnName, clickhouseType]` tuples — pull out the type string
        const columnTypes: (string | null)[] = ((hogqlResponse?.types as unknown[][] | undefined) ?? []).map((t) =>
            Array.isArray(t) ? ((t[1] as string | undefined) ?? null) : null
        )
        return flintChartInput({ columns, columnTypes, rows, chartType })
    }, [hogqlResponse, chartType])

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
                <span className="text-xs text-secondary">Chart type</span>
                <LemonSelect
                    size="small"
                    value={chartType}
                    onChange={setChartType}
                    options={CHART_TYPE_OPTIONS}
                    data-attr="flint-chart-type"
                />
            </div>
            <div className="flex-1 min-h-0 rounded bg-surface-primary p-2">
                <FlintQuillChart input={input} className="h-full" dataAttr="flint-quill-visualization" />
            </div>
        </div>
    )
}
