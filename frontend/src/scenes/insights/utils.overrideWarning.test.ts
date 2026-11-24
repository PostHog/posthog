import { getOverrideWarningPropsForButton } from 'scenes/insights/utils'

import { DataVisualizationNode, HogQLVariable, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'

describe('getOverrideWarningPropsForButton()', () => {
    const sqlInsight = (query: string, variables?: Record<string, HogQLVariable>): DataVisualizationNode => ({
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query, variables },
    })
    const trendsInsight: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.EventsNode, event: '$pageview' }] },
    }
    const endpointVariable: HogQLVariable = { variableId: 'var-1', code_name: 'endpoint', value: 'a' }
    const dateFilter = { date_from: '-24h' }
    const endpointOverride = { 'var-1': { ...endpointVariable, value: 'b' } }

    it.each([
        [
            'SQL without a filters placeholder ignores dashboard filters',
            sqlInsight('SELECT 1'),
            dateFilter,
            null,
            undefined,
            null,
        ],
        [
            'SQL with a filters placeholder uses dashboard filters',
            sqlInsight('SELECT 1 WHERE {filters}'),
            dateFilter,
            null,
            'filters',
            null,
        ],
        [
            'SQL uses a dashboard variable it declares',
            sqlInsight('SELECT {variables.endpoint}', { 'var-1': endpointVariable }),
            null,
            endpointOverride,
            'variables',
            null,
        ],
        [
            'SQL ignores a dashboard variable it does not declare',
            sqlInsight('SELECT 1'),
            null,
            endpointOverride,
            undefined,
            null,
        ],
        ['a regular insight uses dashboard filters', trendsInsight, dateFilter, null, 'filters', null],
        ['a tile uses its own filters', trendsInsight, null, null, 'filters', dateFilter],
        [
            'a tile that ignores dashboard filters and has none of its own',
            trendsInsight,
            dateFilter,
            null,
            undefined,
            { ignoreDashboardFilters: true, explicitDate: true },
        ],
    ])('%s', (_name, query, filtersOverride, variablesOverride, expectedOverrideType, tileFiltersOverride) => {
        expect(
            getOverrideWarningPropsForButton(query, filtersOverride, variablesOverride, tileFiltersOverride).tooltip
        ).toEqual(expectedOverrideType ? expect.stringContaining(`dashboard ${expectedOverrideType}`) : undefined)
    })
})
