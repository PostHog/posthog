import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType, QueryBasedInsightModel } from '~/types'

import { OutputTab } from '../outputPaneLogic'
import { sqlEditorLogic } from '../sqlEditorLogic'
import { insightBuilderLogic } from './insightBuilderLogic'

// endpointLogic uses permanentlyMount() with a keyed logic, which crashes in
// tests without the full React component tree — disable auto-mounting
jest.mock('lib/utils/kea-logic-builders', () => ({
    permanentlyMount: () => () => {},
}))

const TAB_ID = 'builder-test'
const BASE_QUERY = 'SELECT event, amount FROM events'

// A self-consistent saved node: its SQL is (modulo whitespace) what its builder config compiles
// to for its chart type — line charts keep the Rows breakdown, so `plan` survives compilation
const BUILDER_NODE: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: 'SELECT plan AS plan, sum(amount) AS sum_amount FROM (SELECT * FROM payments) GROUP BY plan ORDER BY plan ASC',
    },
    display: ChartDisplayType.ActionsLineGraph,
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
            // Builder recompiles run 'async' so they can hit the query cache — only the explicit
            // Run button forces fresh execution
            .toDispatchActions(sqlLogic, [
                (action) => action.type === sqlLogic.actionTypes.runQuery && action.payload.refreshMode === 'async',
            ])

        const node = sqlLogic.values.sourceQuery
        expect(node.builder).toEqual({
            enabled: true,
            baseQuery: BASE_QUERY,
            rows: [],
            columns: [{ column: 'event', dateGrain: undefined }],
            values: [{ column: 'amount', aggregation: 'sum' }],
            // Snapshot of what the config compiled to — edit detection compares against this
            compiledQuery: node.source.query,
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
                builderDisplay: ChartDisplayType.ActionsLineGraph,
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

    it('rejects an add to a well the chart does not use, with feedback instead of silence', async () => {
        const toastSpy = jest.spyOn(lemonToast, 'info')
        sqlLogic.actions.setQueryInput(BASE_QUERY)
        builderLogic.actions.setBaseSnapshot(BASE_QUERY, null)
        builderLogic.actions.setBuilderDisplay(ChartDisplayType.ActionsBar)

        await expectLogic(builderLogic, () => {
            builderLogic.actions.addField('rows', 'event')
        }).toMatchValues({ rows: [] })

        expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining("doesn't use Breakdown"))
    })

    it('keeps stashed fields when rejecting an add to a well the chart does not use', async () => {
        await expectLogic(builderLogic, () => {
            sqlLogic.actions.setSourceQuery(BUILDER_NODE)
        }).toDispatchActions(['hydrateFromNode'])
        // Bar charts don't use Breakdown, so the hydrated `plan` row becomes a stash — it comes
        // back when the chart type changes back. A rejected add must undo only itself, not eat it.
        builderLogic.actions.setBuilderDisplay(ChartDisplayType.ActionsBar)

        await expectLogic(builderLogic, () => {
            builderLogic.actions.addField('rows', 'event')
        }).toMatchValues({ rows: [{ column: 'plan' }] })
    })

    it('pins the builder display onto the node while wells are empty, without claiming builder', async () => {
        // With `display: Auto` the FORMAT panel's identity would be derived from the response
        // (flipping between table settings and axis pickers); the pin keeps the builder's chart
        // type authoritative from the first render. No `builder` key and no query run: an
        // empty-well session saved as an insight must stay a plain SQL insight.
        sqlLogic.actions.setQueryInput(BASE_QUERY)
        builderLogic.actions.setBaseSnapshot(BASE_QUERY, null)

        await expectLogic(builderLogic, () => {
            builderLogic.actions.applyWells()
        }).delay(400)

        expect(sqlLogic.values.sourceQuery.display).toEqual(ChartDisplayType.ActionsTable)
        expect(sqlLogic.values.sourceQuery.builder).toBeUndefined()

        await expectLogic(builderLogic, () => {
            builderLogic.actions.setBuilderDisplay(ChartDisplayType.ActionsLineGraph)
        })
            .delay(400)
            .toNotHaveDispatchedActions(sqlLogic, ['runQuery'])

        expect(sqlLogic.values.sourceQuery.display).toEqual(ChartDisplayType.ActionsLineGraph)
        expect(sqlLogic.values.sourceQuery.builder).toBeUndefined()
    })

    it('does not re-snapshot an edited buffer when reopening Visualization with fields placed', async () => {
        await expectLogic(builderLogic, () => {
            sqlLogic.actions.setSourceQuery(BUILDER_NODE)
        }).toDispatchActions(['hydrateFromNode'])

        // A half-edited buffer must not silently replace the base the wells were built on —
        // the explicit "Base query changed" banner is the only refresh path once fields exist
        sqlLogic.actions.setQueryInput('SELECT * FROM payments WHERE amount >')

        await expectLogic(builderLogic, () => {
            builderLogic.actions.setActiveTab(OutputTab.Visualization)
        }).toNotHaveDispatchedActions(['refreshBase'])

        expect(builderLogic.values.baseQuery).toEqual('SELECT * FROM payments')
        expect(builderLogic.values.baseOutOfSync).toEqual(true)
    })

    it('hydrates when the builder mounts after the node already landed', async () => {
        // Opening an insight races the canvas mount (lazy chunk, tab restore) against the
        // insight arriving — whichever wins, the wells and chart type must hydrate. This covers
        // node-first: delivered while the builder logic was unmounted, picked up on mount by
        // the sourceQuery value subscription.
        builderLogic.unmount()
        sqlLogic.actions.setSourceQuery(BUILDER_NODE)

        builderLogic = insightBuilderLogic({ tabId: TAB_ID })
        await expectLogic(builderLogic, () => {
            builderLogic.mount()
        })
            .toDispatchActions(['hydrateFromNode'])
            .toMatchValues({
                rows: [{ column: 'plan' }],
                baseQuery: 'SELECT * FROM payments',
                builderDisplay: ChartDisplayType.ActionsLineGraph,
                hydrated: true,
            })
    })

    it('reports unhydrated between a reset and re-hydration, so the preview loads instead of showing empty wells', async () => {
        // On a cold reload the canvas can render between the insight landing and hydration
        // running — `hydrated` is what keeps BuilderPreview on a spinner there instead of the
        // misleading "pick fields" empty state. A fresh non-builder tab counts as hydrated
        // (afterMount seeds it): there is nothing to wait for.
        expect(builderLogic.values.hydrated).toEqual(true)

        // A new object in the tab drops the flag with the wells...
        await expectLogic(builderLogic, () => {
            builderLogic.actions.resetBuilder()
        }).toMatchValues({ hydrated: false })

        // ...and an insight open (reset + immediate re-hydration) lands back on true
        sqlLogic.actions.setSourceQuery(BUILDER_NODE)
        await expectLogic(builderLogic, () => {
            sqlLogic.actions.createTab('SELECT * FROM payments', undefined, {
                short_id: 'abc123',
                name: 'Builder insight',
                query: BUILDER_NODE,
            } as unknown as QueryBasedInsightModel)
        })
            .toDispatchActions(['resetBuilder', 'hydrateFromNode'])
            .toMatchValues({ hydrated: true })
    })

    it('snapshots the compiled SQL into the config so compiler drift cannot orphan saved insights', async () => {
        sqlLogic.actions.setQueryInput(BASE_QUERY)
        builderLogic.actions.setBaseSnapshot(BASE_QUERY, null)

        await expectLogic(builderLogic, () => {
            builderLogic.actions.addField('columns', 'event')
            builderLogic.actions.addField('values', 'amount', { aggregation: 'sum' })
        }).toDispatchActions(sqlLogic, ['setSourceQuery'])

        const node = sqlLogic.values.sourceQuery
        expect(node.builder?.compiledQuery).toEqual(node.source.query)

        // A node whose snapshot matches its SQL hydrates even when today's compiler would emit
        // different SQL for the same config (e.g. an alias was renamed since the insight saved)
        const savedWithOldCompiler: DataVisualizationNode = {
            ...BUILDER_NODE,
            source: { ...BUILDER_NODE.source, query: 'SELECT plan, sum(amount) AS legacy_alias FROM payments' },
            builder: {
                ...BUILDER_NODE.builder!,
                compiledQuery: 'SELECT plan, sum(amount) AS legacy_alias FROM payments',
            },
        }
        await expectLogic(builderLogic, () => {
            sqlLogic.actions.setSourceQuery(savedWithOldCompiler)
        })
            .toDispatchActions(['hydrateFromNode'])
            .toMatchValues({ rows: [{ column: 'plan' }] })
        expect(sqlLogic.values.sourceQuery.builder).not.toBeUndefined()
    })

    it('does not hydrate again when an identical node round-trips through setSourceQuery', async () => {
        await expectLogic(builderLogic, () => {
            sqlLogic.actions.setSourceQuery(BUILDER_NODE)
        }).toDispatchActions(['hydrateFromNode'])

        await expectLogic(builderLogic, () => {
            sqlLogic.actions.setSourceQuery({ ...BUILDER_NODE })
        }).toNotHaveDispatchedActions(['hydrateFromNode'])
    })

    describe('externally edited SQL', () => {
        // The SQL no longer matches what the builder config compiles to — e.g. it was edited
        // outside the builder (via the API, or in the classic editor before editing became
        // content-gated), then saved
        const EDITED_NODE: DataVisualizationNode = {
            ...BUILDER_NODE,
            source: { ...BUILDER_NODE.source, query: 'SELECT edited_elsewhere FROM payments' },
        }

        it('leaves a stale node untouched instead of stripping its builder config', async () => {
            // Staleness is decided once at open time (nodeOpensInBuilder in sqlEditorLogic —
            // a stale insight opens classic and this canvas never hosts it). Stripping the
            // config or rewriting the buffer from here is what used to make the layout
            // oscillate between builder and classic, so a stale node must pass through
            // unhydrated and unmodified.
            await expectLogic(builderLogic, () => {
                sqlLogic.actions.setSourceQuery(EDITED_NODE)
            })
                .toNotHaveDispatchedActions(['hydrateFromNode'])
                .toMatchValues({ rows: [] })

            expect(sqlLogic.values.sourceQuery.builder).toEqual(EDITED_NODE.builder)
            expect(sqlLogic.values.sourceQuery.source.query).toEqual('SELECT edited_elsewhere FROM payments')
            expect(sqlLogic.values.queryInput).toBeNull()
        })

        it("does not attach the previous insight's wells to a legacy insight opened in the same tab", async () => {
            // The wells are per editor tab and would otherwise survive switching insights — the
            // next applyWells then writes the old builder config and its compiled SQL onto an
            // insight that never had one
            await expectLogic(builderLogic, () => {
                sqlLogic.actions.setSourceQuery(BUILDER_NODE)
            }).toDispatchActions(['hydrateFromNode'])

            const legacyNode: DataVisualizationNode = {
                kind: NodeKind.DataVisualizationNode,
                source: { kind: NodeKind.HogQLQuery, query: 'SELECT 99 AS x' },
                display: ChartDisplayType.ActionsBar,
            }
            await expectLogic(builderLogic, () => {
                // The open flow replaces the node, then re-creates the tab for the new object
                sqlLogic.actions.setSourceQuery(legacyNode)
                sqlLogic.actions.createTab('SELECT 99 AS x')
            })
                .toDispatchActions(['resetBuilder'])
                .toMatchValues({ rows: [], measures: [], baseQuery: '' })

            await expectLogic(builderLogic, () => {
                builderLogic.actions.setActiveTab(OutputTab.Visualization)
            }).delay(400)

            expect(sqlLogic.values.sourceQuery.builder).toBeUndefined()
            expect(sqlLogic.values.sourceQuery.source.query).toEqual('SELECT 99 AS x')
        })

        it('keeps hydration when an insight open re-creates the tab with the canvas mounted', async () => {
            // Reloading straight into Visualization mounts the builder before the open flow
            // finishes: the node lands (hydrates), then createTab resets the builder state —
            // the reset must re-hydrate from the node the tab now owns, or the canvas sits on
            // the empty state until a tab flip
            await expectLogic(builderLogic, () => {
                sqlLogic.actions.setSourceQuery(BUILDER_NODE)
            }).toDispatchActions(['hydrateFromNode'])

            await expectLogic(builderLogic, () => {
                sqlLogic.actions.createTab('SELECT * FROM payments', undefined, {
                    short_id: 'abc999',
                    name: 'Builder insight',
                    query: BUILDER_NODE,
                } as unknown as QueryBasedInsightModel)
            })
                .toDispatchActions(['resetBuilder', 'hydrateFromNode'])
                .toMatchValues({ rows: [{ column: 'plan' }], baseQuery: 'SELECT * FROM payments' })
        })

        it('a later consistent insight in the same tab still hydrates', async () => {
            // One externally edited insight must not poison the tab for the next one
            sqlLogic.actions.setSourceQuery(EDITED_NODE)

            await expectLogic(builderLogic, () => {
                sqlLogic.actions.setSourceQuery(BUILDER_NODE)
            })
                .toDispatchActions(['hydrateFromNode'])
                .toMatchValues({ rows: [{ column: 'plan' }], baseQuery: 'SELECT * FROM payments' })
        })
    })
})
