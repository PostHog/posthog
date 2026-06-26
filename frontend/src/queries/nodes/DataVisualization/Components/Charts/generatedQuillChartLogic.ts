import { actions, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import type { ChartSpec } from 'lib/components/ChartSpecRenderer/chartSpec'

import { type ChartSpecMapping, chartSpecFromMapping } from './chartSpecFromMapping'
import type { generatedQuillChartLogicType } from './generatedQuillChartLogicType'

export interface GeneratedQuillChartLogicProps {
    key: string
}

export interface GenerateChartPayload {
    teamId: number
    query: string
    columns: string[]
    columnTypes?: (string | null)[]
    rows: unknown[][]
}

interface SqlChartSpecResponse {
    mapping: ChartSpecMapping
    trace_id: string
    warnings?: string[]
}

function buildRequest(
    prompt: string,
    query: string,
    columns: string[],
    columnTypes: (string | null)[] | undefined,
    rows: unknown[][]
): Record<string, unknown> {
    const sampleRows = rows.slice(0, 20)
    return {
        query,
        prompt: prompt || 'Visualize these results.',
        columns: columns.map((name, i) => ({
            name,
            type: columnTypes?.[i] ?? null,
            sampleValues: sampleRows
                .map((row) => row[i])
                .filter((value) => value != null)
                .slice(0, 5),
        })),
        sampleRows: sampleRows.map((row) => Object.fromEntries(columns.map((name, i) => [name, row[i]]))),
        rowCount: rows.length,
    }
}

export const generatedQuillChartLogic = kea<generatedQuillChartLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'Charts', 'generatedQuillChartLogic']),
    props({} as GeneratedQuillChartLogicProps),
    key((props) => props.key),
    actions({
        setPrompt: (prompt: string) => ({ prompt }),
        generateChart: (payload: GenerateChartPayload) => payload,
    }),
    reducers({
        prompt: ['' as string, { setPrompt: (_, { prompt }) => prompt }],
        lastColumns: [[] as string[], { generateChart: (_, { columns }) => columns }],
        lastRows: [[] as unknown[][], { generateChart: (_, { rows }) => rows }],
    }),
    loaders(({ values }) => ({
        generation: [
            null as SqlChartSpecResponse | null,
            {
                generateChart: async ({ teamId, query, columns, columnTypes, rows }) => {
                    const request = buildRequest(values.prompt, query, columns, columnTypes, rows)
                    return await api.create<SqlChartSpecResponse>(`api/projects/${teamId}/sql_chart_spec`, request)
                },
            },
        ],
    })),
    selectors({
        chartSpec: [
            (s) => [s.generation, s.lastColumns, s.lastRows],
            (generation, lastColumns, lastRows): ChartSpec | null =>
                generation?.mapping ? chartSpecFromMapping(generation.mapping, lastColumns, lastRows) : null,
        ],
        warnings: [(s) => [s.generation], (generation): string[] => generation?.warnings ?? []],
    }),
])
