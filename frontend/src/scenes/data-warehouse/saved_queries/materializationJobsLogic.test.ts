import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'
import { createElement } from 'react'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { MaterializationRunActions } from 'products/data_warehouse/frontend/shared/components/MaterializationRunActions'

import { dataWarehouseViewsLogic } from './dataWarehouseViewsLogic'
import { materializationJobsLogic } from './materializationJobsLogic'

const ELIGIBLE_CHECK = {
    eligible: true,
    key_candidates: ['timestamp', 'id'],
    unique_key_candidates: ['timestamp', 'id', 'event'],
    key_candidate_types: { timestamp: 'datetime', id: 'integer', event: 'string' },
    blockers: [],
    warnings: [],
}

describe('materializationJobsLogic', () => {
    // Role+name queries walk the whole rendered DOM; the buttons carry a data-attr, so query that.
    const buttonByAttr = (attr: string): HTMLElement => {
        const button = document.querySelector(`[data-attr="${attr}"]`)
        if (!button) {
            throw new Error(`No button with data-attr="${attr}"`)
        }
        return button as HTMLElement
    }

    let logic: ReturnType<typeof materializationJobsLogic.build>
    let checkCalls = 0
    // Read on every saved-query fetch, so a test can move the saved cadence between reloads.
    let savedSyncFrequency: string | null = null

    // A plain config builder, not a wrapper around useMocks: a helper calling a use*-named
    // function trips react-hooks/rules-of-hooks in lint.
    function apiMocks({
        isMaterialized,
        incremental = null,
    }: {
        isMaterialized: boolean
        incremental?: Record<string, any> | null
    }): Parameters<typeof useMocks>[0] {
        return {
            get: {
                '/api/environments/:team_id/warehouse_saved_queries/:id/': () => [
                    200,
                    {
                        id: 'view-1',
                        name: 'v1',
                        user_access_level: 'editor',
                        is_materialized: isMaterialized,
                        sync_frequency: savedSyncFrequency,
                        incremental,
                        query: { kind: 'HogQLQuery', query: 'SELECT timestamp, id FROM events' },
                    },
                ],
                '/api/environments/:team_id/data_modeling_jobs': { results: [], count: 0 },
            },
            post: {
                '/api/environments/:team_id/warehouse_saved_queries/check_incremental/': () => {
                    checkCalls += 1
                    return [200, ELIGIBLE_CHECK]
                },
            },
        }
    }

    beforeEach(() => {
        checkCalls = 0
        savedSyncFrequency = null
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DATA_MODELING_INCREMENTAL_VIEWS], {
            [FEATURE_FLAGS.DATA_MODELING_INCREMENTAL_VIEWS]: true,
        })
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
        featureFlagLogic.unmount()
        jest.useRealTimers()
    })

    // Regression: the saved query reloads on every jobs poll. Without the once-per-mount guard the
    // eligibility check fires on each poll, hammering a parse-heavy endpoint. And without the key
    // default, enabling incremental starts from an empty picker.
    it('runs the eligibility check once for an unmaterialized view and defaults the key', async () => {
        useMocks(apiMocks({ isMaterialized: false }))
        logic = materializationJobsLogic({ viewId: 'view-1' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadIncrementalCheckSuccess'])
        expect(checkCalls).toBe(1)
        expect(logic.values.incrementalCheck).toEqual(ELIGIBLE_CHECK)
        expect(logic.values.incrementalDraft.incrementalKey).toBe('timestamp')

        // A later poll reloads the saved query; the check must not fire again.
        logic.actions.loadSavedQuery()
        await expectLogic(logic).toDispatchActions(['loadSavedQuerySuccess']).toFinishAllListeners()
        expect(checkCalls).toBe(1)
    })

    // Regression: a rejected eligibility check used to surface as a "Load incremental check failed"
    // toast on a healthy materialized view. A 4xx is an expected refusal and is not retried; a 5xx is
    // ours to record, and the next savedQuery reload (every jobs poll) retries it.
    it.each([
        [400, { type: 'validation_error', detail: 'Query is not valid.' }, 0, 1],
        [500, { type: 'server_error', detail: 'Something went wrong.' }, 1, 2],
    ])(
        'treats a %s from the eligibility check as "no incremental option" instead of failing',
        async (status, body, captured, checksAfterReload) => {
            const captureException = jest.spyOn(posthog, 'captureException').mockImplementation(() => {})
            let checkCalls = 0
            const mocks = apiMocks({ isMaterialized: true })
            mocks.post = {
                '/api/environments/:team_id/warehouse_saved_queries/check_incremental/': () => {
                    checkCalls += 1
                    return [status, body]
                },
            }
            useMocks(mocks)
            logic = materializationJobsLogic({ viewId: 'view-1' })
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadIncrementalCheck', 'loadIncrementalCheckSuccess'])
                .toNotHaveDispatchedActions(['loadIncrementalCheckFailure'])
            expect(logic.values.incrementalCheck).toBeNull()
            expect(captureException).toHaveBeenCalledTimes(captured)

            logic.actions.loadSavedQuery()
            await expectLogic(logic).toDispatchActions(['loadSavedQuerySuccess']).toFinishAllListeners()
            expect(checkCalls).toBe(checksAfterReload)
        }
    )

    it.each([
        ['the surface is an endpoint', { kind: 'endpoint' as const, flag: true }],
        ['the feature flag is off', { kind: 'view' as const, flag: false }],
    ])('does not run the eligibility check when %s', async (_name, { kind, flag }) => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.DATA_MODELING_INCREMENTAL_VIEWS]: flag,
        })
        useMocks(apiMocks({ isMaterialized: false }))
        logic = materializationJobsLogic({ viewId: 'view-1', kind })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadSavedQuerySuccess']).toFinishAllListeners()
        expect(checkCalls).toBe(0)
    })

    it.each([
        ['flag disabled', 'view' as const, false, false],
        ['endpoint', 'endpoint' as const, true, false],
        ['untouched draft', 'view' as const, true, false],
        ['explicit full refresh', 'view' as const, true, true],
    ])('preserves stored incremental settings unless edited: %s', async (_name, kind, flag, edited) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DATA_MODELING_INCREMENTAL_VIEWS]: flag })
        const incremental = { enabled: true, incremental_key: 'id', unique_key: ['id'], lookback_seconds: 0 }
        const updates: unknown[] = []
        let materializations = 0
        useMocks({
            ...apiMocks({ isMaterialized: false, incremental }),
            patch: {
                '/api/environments/:team_id/warehouse_saved_queries/:id/': async ({ request }) => {
                    updates.push(await request.json())
                    return [200, { id: 'view-1' }]
                },
            },
            post: {
                '/api/environments/:team_id/warehouse_saved_queries/check_incremental/': ELIGIBLE_CHECK,
                '/api/projects/:team_id/warehouse_saved_queries/:id/materialize/': () => {
                    materializations++
                    return [200, {}]
                },
            },
        })
        logic = materializationJobsLogic({ viewId: 'view-1', kind })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSavedQuerySuccess']).toFinishAllListeners()
        if (edited) {
            logic.actions.setIncrementalDraft({ enabled: false })
        }
        render(createElement(MaterializationRunActions, { viewId: 'view-1', kind }))
        await expectLogic(logic).toFinishAllListeners()
        expect(buttonByAttr('node-detail-materialize').getAttribute('aria-disabled')).not.toBe('true')
        await expectLogic(dataWarehouseViewsLogic(), () => {
            fireEvent.click(buttonByAttr('node-detail-materialize'))
        })
            .toDispatchActions(['materializeDataWarehouseSavedQuerySuccess'])
            .toFinishAllListeners()
        expect(updates).toEqual(edited ? [{ incremental: null }] : [])
        expect(materializations).toBe(1)
    })

    // Regression: the refresh-mode editor on a materialized view must start from the saved config,
    // not from the empty draft - otherwise it always shows "Full refresh" and offers a no-op save.
    // But a saved-query repoll must not clobber picks the user is in the middle of changing.
    it('seeds the draft from the saved incremental config until the user edits it', async () => {
        useMocks(
            apiMocks({
                isMaterialized: true,
                incremental: { enabled: true, incremental_key: 'id', unique_key: ['id'], lookback_seconds: 3600 },
            })
        )
        logic = materializationJobsLogic({ viewId: 'view-1' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadSavedQuerySuccess', 'loadIncrementalCheckSuccess'])
        // Materialized views run the check too: switching modes needs the key candidates.
        expect(checkCalls).toBe(1)
        expect(logic.values.incrementalDraft).toEqual({
            enabled: true,
            incrementalKey: 'id',
            uniqueKey: ['id'],
            lookbackSeconds: 3600,
        })

        logic.actions.setIncrementalDraft({ lookbackSeconds: 0 })
        logic.actions.loadSavedQuery()
        await expectLogic(logic).toDispatchActions(['loadSavedQuerySuccess']).toFinishAllListeners()
        expect(logic.values.incrementalDraft.lookbackSeconds).toBe(0)
    })
    it('keeps cadence and mode edits through polling and discards both together', async () => {
        useMocks(apiMocks({ isMaterialized: true }))
        logic = materializationJobsLogic({ viewId: 'view-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadIncrementalCheckSuccess'])
        logic.actions.setSyncFrequencyDraft('12hour')
        logic.actions.setIncrementalDraft({ enabled: true, uniqueKey: ['id'] })
        await expectLogic(logic, () => logic.actions.loadSavedQuery()).toDispatchActions(['loadSavedQuerySuccess'])
        expect(logic.values.hasMaterializationChanges).toBe(true)
        expect(logic.values.syncFrequencyDraft).toBe('12hour')
        expect(logic.values.incrementalDraft.enabled).toBe(true)
        logic.actions.discardMaterializationChanges()
        expect(logic.values.hasMaterializationChanges).toBe(false)
        expect(logic.values.syncFrequencyDraft).toBeNull()
        expect(logic.values.incrementalDraft.enabled).toBe(false)
    })

    // The SQL editor's model modal mounts this logic before a view is open, keyed on an empty
    // string, so it can ask whether there are unsaved settings. That instance has to stay inert:
    // without the viewId guards it would fetch an empty id on every editor render.
    it('fetches nothing and reports no changes without a view id', async () => {
        let fetches = 0
        useMocks({
            get: {
                '/api/environments/:team_id/warehouse_saved_queries/:id/': () => {
                    fetches += 1
                    return [200, { id: 'view-1' }]
                },
                '/api/environments/:team_id/data_modeling_jobs': () => {
                    fetches += 1
                    return [200, { results: [], count: 0 }]
                },
            },
        })
        logic = materializationJobsLogic({ viewId: '' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(fetches).toBe(0)
        expect(logic.values.hasMaterializationChanges).toBe(false)
    })

    it('drops a cadence draft equal to the saved cadence, so a later pause stays paused', async () => {
        savedSyncFrequency = '6hour'
        useMocks(apiMocks({ isMaterialized: true }))
        logic = materializationJobsLogic({ viewId: 'view-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSavedQuerySuccess'])

        logic.actions.setSyncFrequencyDraft('12hour')
        expect(logic.values.hasMaterializationChanges).toBe(true)
        logic.actions.setSyncFrequencyDraft('6hour')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.syncFrequencyDraft).toBeNull()

        savedSyncFrequency = 'never'
        await expectLogic(logic, () => logic.actions.loadSavedQuery()).toDispatchActions(['loadSavedQuerySuccess'])
        expect(logic.values.hasMaterializationChanges).toBe(false)
    })

    it.each([200, 500])('saves cadence and mode together and preserves a failed draft (%s)', async (status) => {
        let submitted: any
        useMocks({
            ...apiMocks({ isMaterialized: true }),
            patch: {
                '/api/environments/:team_id/warehouse_saved_queries/:id/': async ({ request }) => {
                    submitted = await request.json()
                    dataWarehouseViewsLogic.actions.updateDataWarehouseSavedQueryFailed('another-view')
                    expect(logic.values.savingMaterialization).toBe(true)
                    return [status, status === 200 ? { id: 'view-1', ...submitted } : { detail: 'Save failed' }]
                },
            },
        })
        logic = materializationJobsLogic({ viewId: 'view-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadIncrementalCheckSuccess'])
        logic.actions.setSyncFrequencyDraft('12hour')
        logic.actions.setIncrementalDraft({ enabled: true, uniqueKey: ['id'] })
        await expectLogic(logic, () => logic.actions.saveMaterializationChanges()).toDispatchActions([
            'finishSavingMaterialization',
        ])
        expect(submitted).toMatchObject({
            sync_frequency: '12hour',
            incremental: { enabled: true, incremental_key: 'timestamp', unique_key: ['id'] },
        })
        expect(logic.values.savingMaterialization).toBe(false)
        expect(logic.values.hasMaterializationChanges).toBe(status !== 200)
    })
    it.each(['Running', 'Completed'])(
        'polls a %s job at the appropriate interval and recovers from failure',
        async (status) => {
            jest.useFakeTimers()
            let jobsCalls = 0
            let fail = false
            const mocks = apiMocks({ isMaterialized: true })
            mocks.get!['/api/environments/:team_id/data_modeling_jobs'] = () => {
                jobsCalls += 1
                return fail ? [500, { detail: 'Unavailable' }] : [200, { results: [{ id: 'job-1', status }], count: 1 }]
            }
            useMocks(mocks)
            logic = materializationJobsLogic({ viewId: 'view-1' })
            logic.mount()
            await jest.advanceTimersByTimeAsync(0)
            const interval = status === 'Running' ? 10000 : 60000
            await jest.advanceTimersByTimeAsync(interval - 1)
            expect(jobsCalls).toBe(1)
            fail = true
            await jest.advanceTimersByTimeAsync(1)
            expect(logic.values.dataModelingJobsError).toBe(true)
            expect(logic.values.dataModelingJobs?.results[0].status).toBe(status)
            await jest.advanceTimersByTimeAsync(59999)
            expect(jobsCalls).toBe(2)
            fail = false
            await jest.advanceTimersByTimeAsync(1)
            expect(logic.values.dataModelingJobsError).toBe(false)
            expect(jobsCalls).toBe(3)
            logic.unmount()
            jest.advanceTimersByTime(60000)
            expect(jobsCalls).toBe(3)
        }
    )

    it('keeps post-action controls blocked through a failed reload and ignores another view', async () => {
        let fail = false
        let materialized = true
        const mocks = apiMocks({ isMaterialized: true })
        mocks.get!['/api/environments/:team_id/warehouse_saved_queries/:id/'] = () =>
            fail ? [500, { detail: 'Unavailable' }] : [200, { id: 'view-1', is_materialized: materialized }]
        useMocks(mocks)
        logic = materializationJobsLogic({ viewId: 'view-1' })
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadSavedQuerySuccess', 'loadDataModelingJobsSuccess'])
            .toFinishAllListeners()
        dataWarehouseViewsLogic.actions.materializationChanged('other-view')
        expect(logic.values.materializationRefreshPending).toBe(false)
        fail = true
        await expectLogic(logic, () =>
            dataWarehouseViewsLogic.actions.materializationChanged('view-1')
        ).toDispatchActions(['loadSavedQueryFailure', 'loadDataModelingJobsSuccess'])
        expect(logic.values.materializationRefreshPending).toBe(true)
        expect(logic.values.savedQueryError).toBe(true)
        render(createElement(MaterializationRunActions, { viewId: 'view-1' }))
        await expectLogic(logic).toFinishAllListeners()
        expect(screen.getByLabelText('Retry status refresh')).toBeTruthy()
        materialized = false
        fail = false
        await expectLogic(logic, () => {
            fireEvent.click(screen.getByLabelText('Retry status refresh'))
        }).toDispatchActions(['loadSavedQuerySuccess', 'loadDataModelingJobsSuccess'])
        expect(logic.values.materializationRefreshPending).toBe(false)
        expect(logic.values.savedQuery?.is_materialized).toBe(false)
        expect(logic.values.savedQueryError).toBe(false)
    })
    it('ignores a saved query response started before a materialization action', async () => {
        useMocks(apiMocks({ isMaterialized: true }))
        logic = materializationJobsLogic({ viewId: 'view-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSavedQuerySuccess']).toFinishAllListeners()
        const previous = logic.values.savedQuery!
        let resolvePrevious!: (value: typeof previous) => void
        const pending = new Promise<typeof previous>((resolve) => {
            resolvePrevious = resolve
        })
        const fetch = jest
            .spyOn(api.dataWarehouseSavedQueries, 'get')
            .mockImplementationOnce(() => pending)
            .mockResolvedValue({ ...previous, is_materialized: false })
        try {
            logic.actions.loadSavedQuery()
            await expectLogic(logic, () =>
                dataWarehouseViewsLogic.actions.materializationChanged('view-1')
            ).toDispatchActions(['loadSavedQuerySuccess', 'loadDataModelingJobsSuccess'])
            resolvePrevious(previous)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.savedQuery?.is_materialized).toBe(false)
            expect(logic.values.materializationRefreshPending).toBe(false)
        } finally {
            fetch.mockRestore()
        }
    })
})
