import { FEATURE_FLAGS } from 'lib/constants'

import { matchesFlagDefinition } from './flagGating'

const flagKeys = Object.keys(FEATURE_FLAGS) as (keyof typeof FEATURE_FLAGS)[]
const FLAG_A = flagKeys[0]
const FLAG_B = flagKeys[1]

describe('matchesFlagDefinition', () => {
    it.each([
        ['no flag condition', undefined, {}, true],
        ['plain flag enabled', FLAG_A, { [FEATURE_FLAGS[FLAG_A]]: true }, true],
        ['plain flag disabled', FLAG_A, {}, false],
        ['plain flag variant value', FLAG_A, { [FEATURE_FLAGS[FLAG_A]]: 'test' }, true],
        ['negated flag absent', `!${FLAG_A}`, {}, true],
        ['negated flag enabled', `!${FLAG_A}`, { [FEATURE_FLAGS[FLAG_A]]: true }, false],
        ['tuple flag matching value', [[FLAG_A, 'control']], { [FEATURE_FLAGS[FLAG_A]]: 'control' }, true],
        ['tuple flag wrong value', [[FLAG_A, 'control']], { [FEATURE_FLAGS[FLAG_A]]: 'test' }, false],
        ['tuple flag missing', [[FLAG_A, 'control']], {}, false],
        ['all of multiple conditions met', [FLAG_A, `!${FLAG_B}`], { [FEATURE_FLAGS[FLAG_A]]: true }, true],
        ['one of multiple conditions failing', [FLAG_A, FLAG_B], { [FEATURE_FLAGS[FLAG_A]]: true }, false],
    ])('%s', (_name, flagKey, featureFlags, expected) => {
        expect(matchesFlagDefinition(flagKey as any, featureFlags as any)).toBe(expected)
    })
})
