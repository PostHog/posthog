import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { createElement } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DataModelingNode, DataModelingNodeType, DataWarehouseSavedQuery } from '~/types'

import { NodeDetailOverview } from './NodeDetailOverview'
import { NodeDetailQuery } from './NodeDetailQuery'
import { NodeDetailSceneTab, nodeDetailSceneLogic } from './nodeDetailSceneLogic'

const NODE_ID = 'node-1'
const SAVED_QUERY_ID = 'saved-query-1'

function buildNode(type: DataModelingNodeType, overrides: Partial<DataModelingNode> = {}): DataModelingNode {
    return {
        id: NODE_ID,
        name: 'orders',
        type,
        dag: 'dag-1',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        upstream_count: 0,
        downstream_count: 0,
        saved_query_id: type === 'table' || type === 'metric' ? undefined : SAVED_QUERY_ID,
        ...overrides,
    }
}

describe('nodeDetailSceneLogic', () => {
    let logic: ReturnType<typeof nodeDetailSceneLogic.build>
    let flagsLogic: ReturnType<typeof featureFlagLogic.build>
    let node: DataModelingNode
    let savedQuery: Partial<DataWarehouseSavedQuery>

    const mountScene = async (path: string): Promise<void> => {
        router.actions.push(path)
        logic = nodeDetailSceneLogic({ id: NODE_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        node = buildNode('view')
        savedQuery = { id: SAVED_QUERY_ID, name: 'orders', columns: [], is_materialized: false }
        useMocks({
            get: {
                '/api/environments/:team_id/data_modeling_nodes/lineage/': { nodes: [], edges: [] },
                '/api/environments/:team_id/data_modeling_nodes/:id/': () => [200, node],
                '/api/environments/:team_id/warehouse_saved_queries/:id/': () => [200, savedQuery],
            },
        })
        initKeaTests()
        flagsLogic = featureFlagLogic()
        flagsLogic.mount()
        flagsLogic.actions.setFeatureFlags([FEATURE_FLAGS.DATA_QUALITY_CHECKS], {
            [FEATURE_FLAGS.DATA_QUALITY_CHECKS]: true,
        })
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
        flagsLogic.unmount()
    })

    it.each([undefined, {}])(
        'uses node suspension only until saved-query suspension is available (%s)',
        async (savedSuspension) => {
            node = buildNode('matview', {
                suspended: {
                    clickhouse: { at: '2026-09-13T12:00:00Z', reason: 'Source unavailable', job_id: 'job-1' },
                },
            })
            savedQuery = { ...savedQuery, is_materialized: true, status: 'Failed', suspended: savedSuspension }
            await mountScene(urls.nodeDetail(NODE_ID))
            const jobs = materializationJobsLogic({ viewId: SAVED_QUERY_ID })
            jobs.mount()
            try {
                await expectLogic(jobs).toDispatchActions(['loadSavedQuerySuccess'])
                render(createElement(NodeDetailOverview, { id: NODE_ID }))
                expect(screen.queryByText('Suspended') !== null).toBe(savedSuspension === undefined)
            } finally {
                jobs.unmount()
            }
        }
    )

    // A model with no tab in the URL has to land somewhere useful for its kind, and the URL has to
    // say where it landed — otherwise a refresh or a shared link reopens a different tab.
    it.each<[string, DataModelingNodeType, boolean, NodeDetailSceneTab]>([
        ['a materialized view', 'matview', true, 'materialization'],
        ['a plain view', 'view', false, 'query'],
        ['an endpoint', 'endpoint', true, 'query'],
        ['a table', 'table', false, 'lineage'],
    ])('opens %s on its own default tab', async (_case, type, materialized, expectedTab) => {
        node = buildNode(type)
        savedQuery = { ...savedQuery, is_materialized: materialized }

        await mountScene(urls.nodeDetail(NODE_ID))

        expect(logic.values.effectiveTab).toEqual(expectedTab)
        expect(logic.values.currentTab).toEqual(expectedTab)
    })

    it.each(['table', 'metric'] as const)('offers a %s only its lineage, and opens on it', async (type) => {
        node = buildNode(type)

        await mountScene(urls.nodeDetail(NODE_ID))

        expect(logic.values.availableTabs).toEqual(['lineage'])
        expect(logic.values.currentTab).toEqual('lineage')
    })

    it('shows ten columns on each query page', async () => {
        savedQuery = {
            ...savedQuery,
            columns: Array.from({ length: 11 }, (_, index) => ({
                name: `column_${index + 1}`,
                hogql_value: `column_${index + 1}`,
                type: 'string',
                schema_valid: true,
            })),
        }
        await mountScene(urls.nodeDetail(NODE_ID, 'query'))

        render(createElement(NodeDetailQuery, { id: NODE_ID }))

        expect(screen.getByText('column_10')).toBeTruthy()
        expect(screen.queryByText('column_11')).toBeNull()
        expect(screen.getByText('1-10 of 11 columns')).toBeTruthy()

        fireEvent.click(screen.getByLabelText('Next page'))

        expect(screen.queryByText('column_10')).toBeNull()
        expect(screen.getByText('column_11')).toBeTruthy()
        expect(screen.getByText('11 of 11 columns')).toBeTruthy()
    })

    it('lists every tab a saved query supports when data quality checks are on', async () => {
        await mountScene(urls.nodeDetail(NODE_ID))

        expect(logic.values.availableTabs).toEqual(['query', 'lineage', 'materialization', 'tests', 'history'])
    })

    // The tab is gated on the node's saved_query_id, not the loaded saved query, so a load failure
    // leaves it available for its panel to show the error and retry, and a deep link to it holds.
    it('keeps the materialization tab when the saved query fails to load', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/data_modeling_nodes/lineage/': { nodes: [], edges: [] },
                '/api/environments/:team_id/data_modeling_nodes/:id/': () => [200, node],
                '/api/environments/:team_id/warehouse_saved_queries/:id/': () => [500, {}],
            },
        })

        await mountScene(urls.nodeDetail(NODE_ID, 'materialization'))

        expect(logic.values.savedQueryError).toBe(true)
        expect(logic.values.availableTabs).toContain('materialization')
        expect(logic.values.effectiveTab).toEqual('materialization')
    })

    // A failed saved-query request leaves the scene rendering with nothing to read is_materialized
    // from. Reading that absence as "not materialized" would open a matview on Query and print
    // "Materialization: Off" under its own Materialized view tag.
    it('falls back to the node type for materialization when the saved query fails to load', async () => {
        node = buildNode('matview')
        useMocks({
            get: {
                '/api/environments/:team_id/data_modeling_nodes/lineage/': { nodes: [], edges: [] },
                '/api/environments/:team_id/data_modeling_nodes/:id/': () => [200, node],
                '/api/environments/:team_id/warehouse_saved_queries/:id/': () => [500, {}],
            },
        })

        await mountScene(urls.nodeDetail(NODE_ID))

        expect(logic.values.savedQueryError).toBe(true)
        expect(logic.values.isMaterialized).toBe(true)
        expect(logic.values.effectiveTab).toEqual('materialization')
    })

    // Deep links from the data quality overview outlive the flag that created them.
    it('falls back to the default tab when the URL names a tab this model does not have', async () => {
        flagsLogic.actions.setFeatureFlags([], {})

        await mountScene(urls.nodeDetail(NODE_ID, 'tests'))

        expect(logic.values.effectiveTab).toEqual('query')
        expect(logic.values.currentTab).toEqual('query')
    })

    // Clicking through the lineage graph navigates model to model. The outgoing model's logic is
    // still mounted when the next URL lands, and must not adopt the tab meant for its successor.
    it('ignores a route for a different model', async () => {
        await mountScene(urls.nodeDetail(NODE_ID, 'query'))

        router.actions.push(urls.nodeDetail('node-2', 'lineage'))

        expect(logic.values.currentTab).toEqual('query')
    })

    // The node's copy of the run state only advances on a DAG run, so after a Sync now it reports
    // the run before it — and the strip would contradict the materialization tab beside it.
    it('reads the run state from the saved query, falling back to the node', async () => {
        node = buildNode('matview', { last_run_at: '2026-08-06T19:00:00Z', last_run_status: 'Failed' })
        savedQuery = { ...savedQuery, last_run_at: '2026-08-24T15:36:00Z', status: 'Completed' }

        await mountScene(urls.nodeDetail(NODE_ID))

        expect(logic.values.effectiveLastRunAt).toEqual('2026-08-24T15:36:00Z')
        expect(logic.values.effectiveLastRunStatus).toEqual('Completed')
    })

    // The delete runs from a shared component that also renders in the SQL editor, so the page the
    // deleted view owns is the one that has to leave — and only for its own view.
    it.each([
        ['its own view', SAVED_QUERY_ID, '/project/997/models'],
        ['another view', 'saved-query-2', `/project/997${urls.nodeDetail(NODE_ID, 'query')}`],
    ])('leaves for Models when %s is deleted', async (_name, deletedId, expectedPath) => {
        await mountScene(urls.nodeDetail(NODE_ID))

        dataWarehouseViewsLogic.actions.deleteDataWarehouseSavedQuerySuccess([], deletedId)

        expect(router.values.location.pathname).toEqual(expectedPath)
    })

    it('keeps a tab mounted once it has been visited', async () => {
        await mountScene(urls.nodeDetail(NODE_ID))

        router.actions.push(urls.nodeDetail(NODE_ID, 'lineage'))

        expect(logic.values.visitedTabs).toEqual(['query', 'lineage'])
    })
})
