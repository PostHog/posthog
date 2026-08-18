import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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
    let logic: ReturnType<typeof materializationJobsLogic.build>
    let checkCalls = 0

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
                        is_materialized: isMaterialized,
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
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DATA_MODELING_INCREMENTAL_VIEWS], {
            [FEATURE_FLAGS.DATA_MODELING_INCREMENTAL_VIEWS]: true,
        })
    })

    afterEach(() => {
        logic?.unmount()
        featureFlagLogic.unmount()
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
})
