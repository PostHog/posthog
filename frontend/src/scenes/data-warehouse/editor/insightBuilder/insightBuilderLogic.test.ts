import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { sqlEditorLogic } from '../sqlEditorLogic'
import { insightBuilderLogic } from './insightBuilderLogic'

// endpointLogic uses permanentlyMount() with a keyed logic, which crashes in
// tests without the full React component tree — disable auto-mounting
jest.mock('lib/utils/kea-logic-builders', () => ({
    permanentlyMount: () => () => {},
}))

const TAB_ID = 'builder-test'
const BASE_QUERY = 'SELECT event, amount FROM events'

const BUILDER_NODE: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: 'SELECT plan AS plan, sum(amount) AS sum_amount FROM (SELECT * FROM payments) GROUP BY plan ORDER BY plan ASC',
    },
    display: ChartDisplayType.ActionsBar,
    builder: {
        enabled: true,
        baseQuery: 'SELECT * FROM payments',
        rows: [{ column: 'plan' }],
        columns: [],
        values: [{ column: 'amount', aggregation: 'sum' }],
    },
}

describe('insightBuilderLogic', () => {
    let builderLogic: ReturnType<typeof insightBuilderLogic.build>
    let sqlLogic: ReturnType<typeof sqlEditorLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': { results: [] },
                '/api/environments/:team_id/warehouse_saved_queries/': { results: [] },
                '/api/environments/:team_id/data_modeling_dags/': { results: [] },
                '/api/environments/:team_id/data_modeling_nodes/': { results: [] },
                '/api/environments/:team_id/data_modeling_edges/': { results: [] },
                '/api/environments/:team_id/data_modeling_jobs/recent/': [],
                '/api/environments/:team_id/data_modeling_jobs/running/': [],
                '/api/projects/:team_id/external_data_sources/connections/': [],
                '/api/user_home_settings/@me/': {},
            },
            post: {
                '/api/environments/:team_id/query/': [200, { columns: [], types: [], results: [] }],
            },
        })
        initKeaTests()
        sqlLogic = sqlEditorLogic({ tabId: TAB_ID })
        sqlLogic.mount()
        builderLogic = insightBuilderLogic({ tabId: TAB_ID })
        builderLogic.mount()
    })

    afterEach(() => {
        builderLogic.unmount()
        sqlLogic.unmount()
    })

    it('compiles wells into the source query and runs the compiled SQL', async () => {
        sqlLogic.actions.setQueryInput(BASE_QUERY)
        builderLogic.actions.setBaseSnapshot(BASE_QUERY, null)

        await expectLogic(builderLogic, () => {
            builderLogic.actions.addField('rows', 'event')
            builderLogic.actions.addField('values', 'amount', { aggregation: 'sum' })
        })
            .toDispatchActions(sqlLogic, ['setSourceQuery'])
            // Our own compiled node must not bounce back into hydration (that would loop)
            .toNotHaveDispatchedActions(['hydrateFromNode'])
            .toDispatchActions(sqlLogic, ['runQuery'])

        const node = sqlLogic.values.sourceQuery
        expect(node.builder).toEqual({
            enabled: true,
            baseQuery: BASE_QUERY,
            rows: [{ column: 'event', dateGrain: undefined }],
            columns: [],
            values: [{ column: 'amount', aggregation: 'sum' }],
        })
        expect(node.source.query).toContain('sum(amount) AS sum_amount')
        expect(node.source.query).toContain(`FROM (\n${BASE_QUERY}\n)`)
        expect(node.source.query).toContain('GROUP BY event')
        expect(node.display).toEqual(ChartDisplayType.ActionsTable)
        expect(node.chartSettings?.xAxis?.column).toEqual('event')
        expect(node.chartSettings?.yAxis?.[0]?.column).toEqual('sum_amount')
    })

    it('hydrates wells from a saved builder node without re-applying', async () => {
        await expectLogic(builderLogic, () => {
            sqlLogic.actions.setSourceQuery(BUILDER_NODE)
        })
            .toDispatchActions(['hydrateFromNode'])
            .toMatchValues({
                rows: [{ column: 'plan' }],
                measures: [{ column: 'amount', aggregation: 'sum' }],
                builderDisplay: ChartDisplayType.ActionsBar,
                baseQuery: 'SELECT * FROM payments',
            })
            .delay(400)

        // Hydration must not bounce back into apply (which would rewrite the node and loop)
        await expectLogic(builderLogic).toNotHaveDispatchedActions(['applyWells'])
    })

    it('switches to a chart that fits when a new field exceeds the current chart', async () => {
        sqlLogic.actions.setQueryInput(BASE_QUERY)
        builderLogic.actions.setBaseSnapshot(BASE_QUERY, null)
        builderLogic.actions.addField('rows', 'event')
        builderLogic.actions.addField('values', 'amount', { aggregation: 'sum' })
        builderLogic.actions.setBuilderDisplay(ChartDisplayType.ActionsBar)

        await expectLogic(builderLogic, () => {
            builderLogic.actions.addField('columns', 'region')
        })
            .toMatchValues({ builderDisplay: ChartDisplayType.ActionsStackedBar })
            .toDispatchActions(sqlLogic, ['setSourceQuery'])

        // Stacked bar reads the wells inverted: Columns drives the x-axis, Rows the stacks
        const settings = sqlLogic.values.sourceQuery.chartSettings
        expect(settings?.xAxis?.column).toEqual('region')
        expect(settings?.seriesBreakdownColumn).toEqual('event')
    })

    it('keeps a deliberately chosen chart while fields fill toward its requirements', async () => {
        sqlLogic.actions.setQueryInput(BASE_QUERY)
        builderLogic.actions.setBaseSnapshot(BASE_QUERY, null)
        builderLogic.actions.addField('values', 'amount', { aggregation: 'sum' })
        builderLogic.actions.setBuilderDisplay(ChartDisplayType.TwoDimensionalHeatmap)

        await expectLogic(builderLogic, () => {
            // Heatmap still needs a Column — adding the Row moves toward the requirement, not past it
            builderLogic.actions.addField('rows', 'event')
        }).toMatchValues({ builderDisplay: ChartDisplayType.TwoDimensionalHeatmap })
    })

    it('compiles filters into the query and reruns when a filter completes', async () => {
        sqlLogic.actions.setQueryInput(BASE_QUERY)
        builderLogic.actions.setBaseSnapshot(BASE_QUERY, null)
        builderLogic.actions.addField('rows', 'event')
        builderLogic.actions.addField('values', 'amount', { aggregation: 'sum' })
        builderLogic.actions.addField('filters', 'event')

        await expectLogic(builderLogic, () => {
            builderLogic.actions.updateFilter(0, { operator: 'eq', value: 'purchase' })
        }).toDispatchActions(sqlLogic, ['setSourceQuery'])

        const node = sqlLogic.values.sourceQuery
        expect(node.builder?.filters).toEqual([{ column: 'event', operator: 'eq', value: 'purchase' }])
        expect(node.source.query).toContain("WHERE event = 'purchase'")
    })

    it('compiles a bare select-all base against the object itself, dropping the preview LIMIT', async () => {
        sqlLogic.actions.setQueryInput('SELECT * FROM payments LIMIT 100')
        builderLogic.actions.refreshBase()

        await expectLogic(builderLogic, () => {
            builderLogic.actions.addField('rows', 'plan')
            builderLogic.actions.addField('values', 'amount', { aggregation: 'sum' })
        }).toDispatchActions(sqlLogic, ['setSourceQuery'])

        expect(builderLogic.values.baseViewName).toEqual('payments')
        const node = sqlLogic.values.sourceQuery
        expect(node.builder?.baseView).toEqual('payments')
        expect(node.source.query).toContain('FROM payments')
        expect(node.source.query).not.toContain('LIMIT 100')
    })

    it('does not hydrate again when an identical node round-trips through setSourceQuery', async () => {
        await expectLogic(builderLogic, () => {
            sqlLogic.actions.setSourceQuery(BUILDER_NODE)
        }).toDispatchActions(['hydrateFromNode'])

        await expectLogic(builderLogic, () => {
            sqlLogic.actions.setSourceQuery({ ...BUILDER_NODE })
        }).toNotHaveDispatchedActions(['hydrateFromNode'])
    })
})
