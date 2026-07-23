import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeExperimentSessionContextItem } from '../../__mocks__/experiment_session_context'
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
            first_exposure_timestamp: '2026-07-01T10:02:11Z',
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

    it('orders seen experiments by exposure time, breaking ties on signal rank then name', async () => {
        setFlagEnabled(true)
        useMocks({
            get: {
                '/api/projects/:team_id/experiments/session_context/': {
                    session_id: 'session-4',
                    // Deliberately shuffled, and named so a signal-rank-first sort would order them
                    // differently: a control exposed first must still lead a later multi-variant.
                    results: [
                        makeExperimentSessionContextItem({
                            experiment_id: 1,
                            experiment_name: 'Multi late',
                            variants_seen: ['control', 'test'],
                            multiple_variants: true,
                            first_exposure_timestamp: '2026-07-01T10:00:30Z',
                        }),
                        makeExperimentSessionContextItem({
                            experiment_id: 2,
                            experiment_name: 'Control early',
                            variant: 'control',
                            first_exposure_timestamp: '2026-07-01T10:00:00Z',
                        }),
                        makeExperimentSessionContextItem({
                            experiment_id: 3,
                            experiment_name: 'Enrolled only',
                            first_exposure_timestamp: null,
                        }),
                        makeExperimentSessionContextItem({
                            experiment_id: 4,
                            experiment_name: 'Treatment mid',
                            variant: 'test',
                            first_exposure_timestamp: '2026-07-01T10:00:10Z',
                        }),
                        // Ties with 'Control early' — several flags evaluated together at the start.
                        makeExperimentSessionContextItem({
                            experiment_id: 5,
                            experiment_name: 'Tie multi',
                            variants_seen: ['control', 'test'],
                            multiple_variants: true,
                            first_exposure_timestamp: '2026-07-01T10:00:00Z',
                        }),
                    ],
                },
            },
        })
        logic = sessionRecordingExperimentContextLogic({ sessionRecordingId: 'session-4' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadExperimentContextSuccess'])

        expect(logic.values.seenItems.map((item) => item.experiment_name)).toEqual([
            'Tie multi',
            'Control early',
            'Treatment mid',
            'Multi late',
        ])
        expect(logic.values.enrolledItems.map((item) => item.experiment_name)).toEqual(['Enrolled only'])
    })

    it('loads once the feature flag arrives after mount', async () => {
        setFlagEnabled(false)
        logic = sessionRecordingExperimentContextLogic({ sessionRecordingId: 'session-1' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadExperimentContextSuccess']).toMatchValues({
            experimentContext: null,
        })

        setFlagEnabled(true)

        await expectLogic(logic).toDispatchActions(['loadExperimentContextSuccess']).toMatchValues({
            experimentItems: mockResponse.results,
            hasExperimentContext: true,
        })
    })
})
