import type { ChartAssemblyInput } from 'flint-chart/core'
import { actions, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { flintQuillVisualizationLogicType } from './flintQuillVisualizationLogicType'

export interface FlintQuillVisualizationLogicProps {
    key: string
}

export interface GenerateFlintSpecPayload {
    teamId: number
    query: string
    columns: string[]
    columnTypes: (string | null)[]
    rows: unknown[][]
}

export interface SqlFlintSpecResponse {
    chart_spec: ChartAssemblyInput['chart_spec'] | null
    semantic_types?: Record<string, string>
    narrative?: string | null
    trace_id: string
    warnings?: string[]
}

export const flintQuillVisualizationLogic = kea<flintQuillVisualizationLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'Charts', 'flintQuillVisualizationLogic']),
    props({} as FlintQuillVisualizationLogicProps),
    key((props) => props.key),
    actions({
        setChartType: (chartType: string | null) => ({ chartType }),
        setPrompt: (prompt: string) => ({ prompt }),
        generateSpec: (payload: GenerateFlintSpecPayload) => payload,
    }),
    reducers({
        // null = infer the chart type from the result shape
        chartType: [
            null as string | null,
            {
                setChartType: (_, { chartType }) => chartType,
                // A fresh generation decides its own chart type; drop any manual override
                generateSpecSuccess: () => null,
            },
        ],
        prompt: ['' as string, { setPrompt: (_, { prompt }) => prompt }],
        lastColumns: [[] as string[], { generateSpec: (_, { columns }) => columns }],
        lastRows: [[] as unknown[][], { generateSpec: (_, { rows }) => rows }],
    }),
    loaders(({ values }) => ({
        generation: [
            null as SqlFlintSpecResponse | null,
            {
                generateSpec: async ({ teamId, query, columns, columnTypes, rows }) => {
                    const sampleRows = rows.slice(0, 20)
                    return await api.create<SqlFlintSpecResponse>(`api/projects/${teamId}/sql_flint_spec`, {
                        query,
                        prompt: values.prompt,
                        columns: columns.map((name, i) => ({
                            name,
                            type: columnTypes[i] ?? null,
                            sampleValues: sampleRows
                                .map((row) => row[i])
                                .filter((value) => value != null)
                                .slice(0, 5),
                        })),
                        rowCount: rows.length,
                    })
                },
            },
        ],
    })),
    selectors({
        /** Flint input from the generated spec plus the real rows — null until a generation succeeds. */
        generatedInput: [
            (s) => [s.generation, s.lastColumns, s.lastRows],
            (
                generation: SqlFlintSpecResponse | null,
                lastColumns: string[],
                lastRows: unknown[][]
            ): ChartAssemblyInput | null => {
                if (!generation?.chart_spec || lastColumns.length === 0) {
                    return null
                }
                const values = lastRows.map((row) => Object.fromEntries(lastColumns.map((name, i) => [name, row[i]])))
                return {
                    data: { values },
                    semantic_types: generation.semantic_types ?? {},
                    chart_spec: generation.chart_spec,
                }
            },
        ],
        narrative: [(s) => [s.generation], (generation): string | null => generation?.narrative ?? null],
        warnings: [(s) => [s.generation], (generation): string[] => generation?.warnings ?? []],
    }),
])
