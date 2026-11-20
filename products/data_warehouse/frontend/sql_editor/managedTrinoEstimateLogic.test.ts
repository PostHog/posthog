import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import type { DataVisualizationNode } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import type { QueryEstimateResponseApi } from '../generated/api.schemas'
import { estimateWarnings } from './estimateFormat'
import { ESTIMATE_DEBOUNCE_MS, managedTrinoEstimateLogic } from './managedTrinoEstimateLogic'

const GIB = 1024 ** 3

function estimateFor(upperBoundGib: number): QueryEstimateResponseApi {
    return {
        tables: [{ catalog: 'c', schema: 's', table: 'events', size_bytes: upperBoundGib * GIB, has_filter: false }],
        upper_bound_bytes: upperBoundGib * GIB,
        estimated_cost_usd: '0.29',
        cap_bytes: null,
        exceeds_cap: false,
        complete: true,
        warnings: [],
    }
}

describe('managedTrinoEstimateLogic', () => {
    const tabId = 'estimate-tab'

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]: true })
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    function mountOnManagedTrino(): ReturnType<typeof managedTrinoEstimateLogic.build> {
        const editor = sqlEditorLogic({ tabId })
        editor.mount()
        editor.actions.setExecutionTarget('managed_trino')
        const logic = managedTrinoEstimateLogic({ tabId })
        logic.mount()
        return logic
    }

    it('estimates once after edits stop and keeps only the latest response', async () => {
        const first = new Promise<QueryEstimateResponseApi>(() => {})
        const spy = jest
            .spyOn(api, 'managedWarehouseConsoleEstimateCreate')
            .mockReturnValueOnce(first)
            .mockResolvedValueOnce(estimateFor(120))
        const logic = mountOnManagedTrino()

        sqlEditorLogic({ tabId }).actions.setQueryInput('select 1')
        await jest.advanceTimersByTimeAsync(ESTIMATE_DEBOUNCE_MS)
        sqlEditorLogic({ tabId }).actions.setQueryInput('select 2')
        await jest.advanceTimersByTimeAsync(ESTIMATE_DEBOUNCE_MS)

        await expectLogic(logic).toMatchValues({
            estimateStatus: 'ready',
            estimate: expect.objectContaining({ upper_bound_bytes: 120 * GIB }),
        })
        expect(spy).toHaveBeenCalledTimes(2)
        expect(spy.mock.calls[1][1]).toMatchObject({ query: 'select 2' })
    })

    it('refreshes when the query changes through setSourceQuery and captures one event per distinct result', async () => {
        const spy = jest.spyOn(api, 'managedWarehouseConsoleEstimateCreate').mockResolvedValue(estimateFor(120))
        const capture = jest.spyOn(posthog, 'capture')
        const logic = mountOnManagedTrino()
        const editor = sqlEditorLogic({ tabId })
        const withQuery = (query: string): DataVisualizationNode => ({
            ...editor.values.sourceQuery,
            source: { ...editor.values.sourceQuery.source, kind: NodeKind.HogQLQuery, query },
        })

        editor.actions.setSourceQuery(withQuery('select 1'))
        await jest.advanceTimersByTimeAsync(ESTIMATE_DEBOUNCE_MS)
        editor.actions.setSourceQuery(withQuery('select 1'))
        await jest.advanceTimersByTimeAsync(ESTIMATE_DEBOUNCE_MS)
        editor.actions.setSourceQuery(withQuery('select 2'))
        await jest.advanceTimersByTimeAsync(ESTIMATE_DEBOUNCE_MS)

        await expectLogic(logic).toMatchValues({ estimateStatus: 'ready' })
        expect(spy).toHaveBeenCalledTimes(2)
        expect(spy.mock.calls.map((call) => call[1].query)).toEqual(['select 1', 'select 2'])
        expect(capture.mock.calls.filter(([event]) => event === 'sql editor estimate shown')).toHaveLength(2)
    })

    it('hides the estimate when the request fails', async () => {
        jest.spyOn(api, 'managedWarehouseConsoleEstimateCreate').mockRejectedValue(new Error('boom'))
        const logic = mountOnManagedTrino()

        sqlEditorLogic({ tabId }).actions.setQueryInput('select 1')
        await jest.advanceTimersByTimeAsync(ESTIMATE_DEBOUNCE_MS)

        await expectLogic(logic).toMatchValues({ estimateStatus: 'error', estimate: null })
    })

    it('does nothing without the console flag', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        const spy = jest.spyOn(api, 'managedWarehouseConsoleEstimateCreate')
        const logic = mountOnManagedTrino()

        sqlEditorLogic({ tabId }).actions.setQueryInput('select 1')
        await jest.advanceTimersByTimeAsync(ESTIMATE_DEBOUNCE_MS)

        await expectLogic(logic).toMatchValues({ estimateEnabled: false, estimateStatus: 'idle' })
        expect(spy).not.toHaveBeenCalled()
    })
})

describe('estimateWarnings', () => {
    it('names the largest unfiltered table, the cap and unknown sizes', () => {
        const warnings = estimateWarnings({
            tables: [
                { catalog: 'c', schema: 's', table: 'events', size_bytes: 175 * GIB, has_filter: false },
                { catalog: 'c', schema: 's', table: 'persons', size_bytes: 2 * GIB, has_filter: false },
                { catalog: 'c', schema: 's', table: 'a', size_bytes: null, has_filter: true },
                { catalog: 'c', schema: 's', table: 'b', size_bytes: null, has_filter: true },
            ],
            upper_bound_bytes: 177 * GIB,
            estimated_cost_usd: null,
            cap_bytes: 50 * GIB,
            exceeds_cap: true,
            complete: false,
            warnings: ['exceeds_cap', 'no_filter_on_large_table', 'size_unknown'],
        })

        expect(warnings.map((w) => [w.tone, w.text])).toEqual([
            ['danger', 'Over your 50.00 GiB per-query limit. This query will be stopped.'],
            ['warning', 'No filter on events (175.00 GiB). Add a time filter to scan less.'],
            ['muted', 'Size unknown for 2 tables'],
        ])
    })
})
