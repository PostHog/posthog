import { type FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { type SourceConfig } from '~/queries/schema/schema-general'

import { shouldShowConnector } from './nonHogFunctionTemplatesLogic'

describe('shouldShowConnector', () => {
    const make = (
        overrides: Partial<Pick<SourceConfig, 'featureFlag' | 'unreleasedSource'>>
    ): Pick<SourceConfig, 'featureFlag' | 'unreleasedSource'> =>
        overrides as Pick<SourceConfig, 'featureFlag' | 'unreleasedSource'>

    // The fixture flag key isn't a real FeatureFlagKey, so cast through unknown to
    // satisfy strict typing — the predicate only does an indexed lookup, so the key
    // identity doesn't matter for the logic.
    const flagsOn = { 'my-flag': true } as unknown as FeatureFlagsSet
    const flagsOff = { 'my-flag': false } as unknown as FeatureFlagsSet
    const noFlags: FeatureFlagsSet = {}

    it.each([
        ['no feature flag, released', make({}), noFlags, true],
        ['no feature flag, unreleased', make({ unreleasedSource: true }), noFlags, true],
        ['flagged released, flag on', make({ featureFlag: 'my-flag' }), flagsOn, true],
        ['flagged released, flag off', make({ featureFlag: 'my-flag' }), flagsOff, false],
        ['flagged released, flag undefined', make({ featureFlag: 'my-flag' }), noFlags, false],
        ['flagged unreleased, flag on', make({ featureFlag: 'my-flag', unreleasedSource: true }), flagsOn, true],
        [
            'flagged unreleased, flag off (regression case — must stay visible for Notify me)',
            make({ featureFlag: 'my-flag', unreleasedSource: true }),
            flagsOff,
            true,
        ],
        ['flagged unreleased, flag undefined', make({ featureFlag: 'my-flag', unreleasedSource: true }), noFlags, true],
    ])('%s', (_label, connector, flags, expected) => {
        expect(shouldShowConnector(connector, flags)).toBe(expected)
    })
})
