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
            // Columns is the grouping dimension (x-axis); Rows is the breakdown
            builderLogic.actions.addField('columns', 'event')
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
            rows: [],
            columns: [{ column: 'event', dateGrain: undefined }],
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

    it('picks a starting chart for the first field but never auto-switches afterward', async () => {
        sqlLogic.actions.setQueryInput(BASE_QUERY)
        builderLogic.actions.setBaseSnapshot(BASE_QUERY, null)

        // First field on a fresh (Table) builder picks a sensible chart
        builderLogic.actions.addField('rows', 'event')
        builderLogic.actions.addField('values', 'amount', { aggregation: 'sum' })
        builderLogic.actions.setBuilderDisplay(ChartDisplayType.ActionsBar)

        // Chart type is now primary — adding a Column does not switch the chart away from bar
        await expectLogic(builderLogic, () => {
            builderLogic.actions.addField('columns', 'region')
        }).toMatchValues({ builderDisplay: ChartDisplayType.ActionsBar })
    })

    it('compiles a numeric bin width into the source query', async () => {
        sqlLogic.actions.setQueryInput(BASE_QUERY)
        builderLogic.actions.setBaseSnapshot(BASE_QUERY, null)
        // A numeric dimension on the x-axis (Columns) can be bucketed into fixed-width bins
        builderLogic.actions.addField('columns', 'amount')
        builderLogic.actions.addField('values', 'amount', { aggregation: 'sum' })

        await expectLogic(builderLogic, () => {
            builderLogic.actions.setNumericBinWidth('columns', 0, 10)
        }).toDispatchActions(sqlLogic, ['setSourceQuery'])

        const node = sqlLogic.values.sourceQuery
        expect(node.builder?.columns).toEqual([{ column: 'amount', numericBinWidth: 10, dateGrain: undefined }])
        expect(node.source.query).toContain('floor(amount / 10) * 10')
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
