import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, Experiment } from '~/types'

import { experimentsReplayLinkabilityRetrieve } from 'products/experiments/frontend/generated/api'

import { viewRecordingsLinkabilityLogic } from './viewRecordingsLinkabilityLogic'

jest.mock('products/experiments/frontend/generated/api', () => ({
    experimentsReplayLinkabilityRetrieve: jest.fn(),
}))

const experimentBase = {
    id: 1,
    name: 'test experiment',
    feature_flag_key: 'my-flag',
    exposure_criteria: undefined,
    filters: {},
    metrics: [],
    metrics_secondary: [],
    primary_metrics_ordered_uuids: null,
    secondary_metrics_ordered_uuids: null,
    saved_metrics_ids: [],
    saved_metrics: [],
    parameters: {},
    secondary_metrics: [],
    created_at: null,
    created_by: null,
    updated_at: null,
    start_date: '2026-01-01T00:00:00Z',
    user_access_level: AccessControlLevel.Editor,
} satisfies Experiment

describe('viewRecordingsLinkabilityLogic', () => {
    let logic: ReturnType<typeof viewRecordingsLinkabilityLogic.build>
    let seenTogetherSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        seenTogetherSpy = jest.spyOn(api.propertyDefinitions, 'seenTogether')
        ;(experimentsReplayLinkabilityRetrieve as jest.Mock).mockClear()
        ;(experimentsReplayLinkabilityRetrieve as jest.Mock).mockResolvedValue({
            exposure_event_linkable: true,
            flag_property_linkable: null,
            max_window_days: 7,
        })
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('checks $session_id linkability on mount and flags only events explicitly seen without it', async () => {
        seenTogetherSpy.mockResolvedValue({ purchase: false })
        logic = viewRecordingsLinkabilityLogic({
            experiment: {
                ...experimentBase,
                metrics: [
                    {
                        kind: NodeKind.ExperimentMetric,
                        metric_type: ExperimentMetricType.MEAN,
                        source: { kind: NodeKind.EventsNode, event: 'purchase', name: 'purchase' },
                    },
                ],
            } satisfies Experiment,
        })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ linkabilityLoaded: true })
        expect(seenTogetherSpy).toHaveBeenCalledWith({
            eventNames: ['$feature_flag_called', 'purchase'],
            propertyDefinitionName: '$session_id',
        })
        // $feature_flag_called is absent from the response: absent keys stay linkable
        expect(logic.values.unlinkableEventNames).toEqual(new Set(['purchase']))
    })

    // The project-wide `seen_together` fact reports $feature_flag_called linkable on the strength
    // of any one client-evaluated flag, so without the flag-scoped verdict a server-evaluated
    // experiment reads as linkable and its recordings filter matches nothing.
    it('reads the exposure and its stand-in from the flag-scoped check, not the event name', async () => {
        seenTogetherSpy.mockResolvedValue({})
        ;(experimentsReplayLinkabilityRetrieve as jest.Mock).mockResolvedValue({
            exposure_event_linkable: false,
            flag_property_linkable: false,
            max_window_days: 7,
        })
        logic = viewRecordingsLinkabilityLogic({ experiment: experimentBase })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            exposureSessionLinkable: false,
            exposureFallbackLinkable: false,
        })
        expect(logic.values.unlinkableEventNames).toEqual(new Set())
    })

    // Both leave the verdicts unknown, but only the first is a defect worth reporting: swallowing
    // it would hide a broken scan behind the project-wide answer this check exists to replace.
    it.each([
        ['a refused scan', new ApiError('refused', 500), 'loadFlagCoverageFailure'],
        ['an endpoint the backend does not serve yet', new ApiError('not found', 404), 'loadFlagCoverageSuccess'],
    ])('leaves both verdicts unknown on %s, so callers fail open', async (_, error, expectedAction) => {
        seenTogetherSpy.mockResolvedValue({})
        ;(experimentsReplayLinkabilityRetrieve as jest.Mock).mockRejectedValue(error)
        logic = viewRecordingsLinkabilityLogic({ experiment: experimentBase })
        logic.mount()

        await expectLogic(logic).toDispatchActions([expectedAction]).toFinishAllListeners().toMatchValues({
            exposureSessionLinkable: null,
            exposureFallbackLinkable: null,
        })
    })
})
