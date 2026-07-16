import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, Experiment } from '~/types'

import { viewRecordingsLinkabilityLogic } from './viewRecordingsLinkabilityLogic'

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
    user_access_level: AccessControlLevel.Editor,
} satisfies Experiment

describe('viewRecordingsLinkabilityLogic', () => {
    let logic: ReturnType<typeof viewRecordingsLinkabilityLogic.build>
    let seenTogetherSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        seenTogetherSpy = jest.spyOn(api.propertyDefinitions, 'seenTogether')
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

    it('skips the API call when there is no plain event to check', async () => {
        logic = viewRecordingsLinkabilityLogic({
            experiment: {
                ...experimentBase,
                exposure_criteria: {
                    exposure_config: { kind: NodeKind.ActionsNode, id: 123, name: 'action1' },
                },
                metrics: [
                    {
                        kind: NodeKind.ExperimentMetric,
                        metric_type: ExperimentMetricType.MEAN,
                        source: { kind: NodeKind.ActionsNode, id: 123, name: 'action1' },
                    },
                ],
            } satisfies Experiment,
        })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ linkabilityLoaded: true })
        expect(seenTogetherSpy).not.toHaveBeenCalled()
        expect(logic.values.unlinkableEventNames).toEqual(new Set())
    })
})
