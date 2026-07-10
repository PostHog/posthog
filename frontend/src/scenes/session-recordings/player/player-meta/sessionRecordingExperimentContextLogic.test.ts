import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { sessionRecordingExperimentContextLogic } from './sessionRecordingExperimentContextLogic'

const mockResponse = {
    session_id: 'session-1',
    results: [
        {
            experiment_id: 123,
            experiment_name: 'Checkout CTA copy',
            flag_key: 'checkout-cta',
            variant: 'test',
            variants_seen: ['control', 'test'],
            multiple_variants: true,
            first_flag_evaluation_timestamp: '2026-07-01T10:02:11Z',
            experiment_start_date: '2026-06-01T00:00:00Z',
            experiment_end_date: null,
        },
    ],
}

describe('sessionRecordingExperimentContextLogic', () => {
    let logic: ReturnType<typeof sessionRecordingExperimentContextLogic.build>

    const setFlagEnabled = (enabled: boolean): void => {
        featureFlagLogic.actions.setFeatureFlags(
            enabled ? [FEATURE_FLAGS.REPLAY_EXPERIMENT_CONTEXT] : [],
            enabled ? { [FEATURE_FLAGS.REPLAY_EXPERIMENT_CONTEXT]: true } : {}
        )
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/experiments/session_context/': mockResponse,
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
    })

    it('derives items and the multi-variant warning from the response', async () => {
        setFlagEnabled(true)
        logic = sessionRecordingExperimentContextLogic({ sessionRecordingId: 'session-1' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadExperimentContextSuccess']).toMatchValues({
            experimentItems: mockResponse.results,
            hasExperimentContext: true,
            hasMultipleVariantWarning: true,
        })
    })

    it('has no context when the response is empty', async () => {
        setFlagEnabled(true)
        useMocks({
            get: {
                '/api/projects/:team_id/experiments/session_context/': { session_id: 'session-2', results: [] },
            },
        })
        logic = sessionRecordingExperimentContextLogic({ sessionRecordingId: 'session-2' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadExperimentContextSuccess']).toMatchValues({
            experimentItems: [],
            hasExperimentContext: false,
            hasMultipleVariantWarning: false,
        })
    })

    it('does not fetch when the feature flag is off', async () => {
        setFlagEnabled(false)
        logic = sessionRecordingExperimentContextLogic({ sessionRecordingId: 'session-3' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadExperimentContextSuccess']).toMatchValues({
            experimentContext: null,
            hasExperimentContext: false,
        })
    })
})
