import { ExperimentEventExposureConfig, ExperimentExposureCriteria, NodeKind } from '~/queries/schema/schema-general'

import {
    exposureEventLabel,
    getActivationConfig,
    getExposureEventAndProperty,
    isDefaultExposureConfig,
    resolvedExposureEvent,
} from './exposureContract'

describe('exposureContract', () => {
    it('uses the rollout event for a local draft without a server-resolved event', () => {
        expect(resolvedExposureEvent({}, '$experiment_exposure')).toBe('$experiment_exposure')
    })

    it('prefers the server-resolved event over the local draft fallback', () => {
        expect(resolvedExposureEvent({ resolved_exposure_event: '$feature_flag_called' }, '$experiment_exposure')).toBe(
            '$feature_flag_called'
        )
    })

    it.each([
        ['$experiment_exposure', 'Experiment exposure'],
        ['$feature_flag_called', 'Feature flag is called'],
    ])('labels %s as %s', (event, expectedLabel) => {
        expect(exposureEventLabel(event)).toBe(expectedLabel)
    })

    it.each([
        [
            'stored default config',
            {
                kind: NodeKind.ExperimentEventExposureConfig,
                event: '$feature_flag_called',
                properties: [],
            },
            true,
        ],
        [
            'custom event config',
            { kind: NodeKind.ExperimentEventExposureConfig, event: 'checkout_started', properties: [] },
            false,
        ],
        ['action config', { kind: NodeKind.ActionsNode, id: 42 }, false],
    ])('identifies %s for exposure labels', (_name, exposureConfig, expected) => {
        expect(
            isDefaultExposureConfig(exposureConfig as NonNullable<ExperimentExposureCriteria['exposure_config']>)
        ).toBe(expected)
    })

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

    // The rollout swaps the default event server-side, so the default branches must name the
    // resolved event while a custom event stays untouched.
    it.each<[string, ExperimentExposureCriteria | undefined, string | null]>([
        ['no exposure config', undefined, '$experiment_exposure'],
        [
            'default $feature_flag_called config',
            {
                exposure_config: {
                    kind: NodeKind.ExperimentEventExposureConfig,
                    event: '$feature_flag_called',
                    properties: [],
                },
            },
            '$experiment_exposure',
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
            'checkout_started',
        ],
        ['action config', { exposure_config: { kind: NodeKind.ActionsNode, id: 42 } }, null],
    ])('uses the resolved default event for %s', (_name, exposureCriteria, expectedEvent) => {
        expect(
            getExposureEventAndProperty({
                featureFlagKey: 'my-flag',
                exposureCriteria,
                resolvedExposureEvent: '$experiment_exposure',
            }).event
        ).toBe(expectedEvent)
    })

    // Mirrors the backend `has_activation_config` gate: activation only composes with the
    // default exposure, so a custom exposure_config must disable it.
    const activationConfig: ExperimentEventExposureConfig = {
        kind: NodeKind.ExperimentEventExposureConfig,
        event: 'activated',
        properties: [],
    }
    it.each<[string, ExperimentExposureCriteria | undefined, boolean]>([
        ['no criteria', undefined, false],
        ['activation alone', { activation_config: activationConfig }, true],
        [
            'activation with the stored default exposure config',
            {
                exposure_config: {
                    kind: NodeKind.ExperimentEventExposureConfig,
                    event: '$feature_flag_called',
                    properties: [],
                },
                activation_config: activationConfig,
            },
            true,
        ],
        [
            'activation with a pinned $experiment_exposure config',
            {
                exposure_config: {
                    kind: NodeKind.ExperimentEventExposureConfig,
                    event: '$experiment_exposure',
                    properties: [],
                },
                activation_config: activationConfig,
            },
            true,
        ],
        [
            'activation ignored under a custom exposure config',
            {
                exposure_config: {
                    kind: NodeKind.ExperimentEventExposureConfig,
                    event: 'checkout_started',
                    properties: [],
                },
                activation_config: activationConfig,
            },
            false,
        ],
        [
            'activation ignored under an action exposure config',
            {
                exposure_config: { kind: NodeKind.ActionsNode, id: 42 },
                activation_config: activationConfig,
            },
            false,
        ],
    ])('resolves the activation config for %s', (_name, exposureCriteria, expectActive) => {
        expect(getActivationConfig(exposureCriteria)).toEqual(expectActive ? activationConfig : undefined)
    })
})
