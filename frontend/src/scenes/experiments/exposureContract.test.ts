import { ExperimentExposureCriteria, NodeKind } from '~/queries/schema/schema-general'

import { getExposureEventAndProperty } from './exposureContract'

describe('exposureContract', () => {
    // Guards the three-way branch that mirrors the backend `get_exposure_event_and_property`:
    // action configs must yield `event: null` (actions match multiple events) so callers never
    // filter action-based exposures down to a single event name.
    it.each<[string, ExperimentExposureCriteria | undefined, { event: string | null; variantProperty: string }]>([
        ['no exposure config', undefined, { event: '$feature_flag_called', variantProperty: '$feature_flag_response' }],
        [
            'default $feature_flag_called config',
            {
                exposure_config: {
                    kind: NodeKind.ExperimentEventExposureConfig,
                    event: '$feature_flag_called',
                    properties: [],
                },
            },
            { event: '$feature_flag_called', variantProperty: '$feature_flag_response' },
        ],
        [
            'custom event config',
            {
                exposure_config: {
                    kind: NodeKind.ExperimentEventExposureConfig,
                    event: 'checkout_started',
                    properties: [],
                },
            },
            { event: 'checkout_started', variantProperty: '$feature/my-flag' },
        ],
        [
            'action config',
            { exposure_config: { kind: NodeKind.ActionsNode, id: 42 } },
            { event: null, variantProperty: '$feature/my-flag' },
        ],
    ])('resolves the exposure event and variant property for %s', (_name, exposureCriteria, expected) => {
        expect(getExposureEventAndProperty({ featureFlagKey: 'my-flag', exposureCriteria })).toEqual(expected)
    })
})
