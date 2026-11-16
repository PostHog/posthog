import { FeatureFlagRulesV2DraftRule, PropertyFilterType, PropertyOperator } from '~/types'

import { duplicatedRule, rulesV2CatchAllRule, rulesV2ShadowingRules } from './featureFlagRulesV2Draft'

const EMAIL = {
    key: 'email',
    type: PropertyFilterType.Person,
    value: '@example.com',
    operator: PropertyOperator.IContains,
}
const COUNTRY = { key: 'country', type: PropertyFilterType.Person, value: ['NO'], operator: PropertyOperator.Exact }
const INCOMPLETE = { key: 'plan', type: PropertyFilterType.Person, value: null, operator: PropertyOperator.Exact }
const PLAN_IS_SET = { key: 'plan', type: PropertyFilterType.Person, value: null, operator: PropertyOperator.IsSet }

const release = (properties: any[] = []): FeatureFlagRulesV2DraftRule => ({
    rule_type: 'targeted_release',
    targeting: { properties },
    value: true,
})
const rollout = (
    rolloutPercentage: number,
    onRolloutMiss: 'continue' | 'return_default',
    properties: any[] = []
): FeatureFlagRulesV2DraftRule => ({
    rule_type: 'percentage_rollout',
    targeting: { properties },
    value: true,
    rollout_percentage: rolloutPercentage,
    on_rollout_miss: onRolloutMiss,
    assignment_algorithm: 'sha1_60_v1',
})
const experiment = (paused: boolean, rolloutPercentage: number): FeatureFlagRulesV2DraftRule => ({
    rule_type: 'experiment',
    targeting: { properties: [] },
    paused,
    rollout_percentage: rolloutPercentage,
    on_rollout_miss: 'continue',
    assignment_algorithm: 'sha1_60_v1',
    variants: [
        { key: 'control', weight: 50, value: false },
        { key: 'test', weight: 50, value: true },
    ],
})

describe('rulesV2ShadowingRules', () => {
    it.each([
        ['a release to everyone hides any later rule', [release(), release([EMAIL])], [null, 0]],
        ['a narrower earlier rule hides nothing', [release([EMAIL]), release()], [null, null]],
        [
            'an earlier rule with a subset of the conditions hides',
            [release([EMAIL]), release([EMAIL, COUNTRY])],
            [null, 0],
        ],
        ['unrelated conditions are not compared', [release([EMAIL]), release([COUNTRY])], [null, null]],
        ['a partial rollout that continues hides nothing', [rollout(50, 'continue'), release()], [null, null]],
        ['a partial rollout that returns the default hides', [rollout(50, 'return_default'), release()], [null, 0]],
        ['a full rollout hides', [rollout(100, 'continue'), release()], [null, 0]],
        ['a paused experiment hides', [experiment(true, 50), release()], [null, 0]],
        ['a running partial experiment that continues hides nothing', [experiment(false, 50), release()], [null, null]],
        [
            'an incomplete condition matches no one, so it hides nothing',
            [release([INCOMPLETE]), release()],
            [null, null],
        ],
        [
            'a set check takes no value, so it is complete and hides',
            [release([PLAN_IS_SET]), release([PLAN_IS_SET, EMAIL])],
            [null, 0],
        ],
        ['the first hiding rule is named', [release(), release(), release()], [null, 0, 0]],
    ])('%s', (_, rules, expected) => {
        expect(rulesV2ShadowingRules(rules)).toEqual(expected)
    })
})

describe('rulesV2CatchAllRule', () => {
    it('finds the first rule that decides the value for everyone', () => {
        expect(rulesV2CatchAllRule([release([EMAIL]), rollout(25, 'return_default'), release()])).toBe(1)
    })

    it('finds none when every rule lets someone through', () => {
        expect(rulesV2CatchAllRule([])).toBeNull()
        expect(rulesV2CatchAllRule([release([EMAIL]), rollout(25, 'continue')])).toBeNull()
    })
})

describe('duplicatedRule', () => {
    it('drops the id of a targeted release', () => {
        expect(duplicatedRule({ ...release([EMAIL]), id: 'rule-1', description: 'Staff' })).toEqual({
            ...release([EMAIL]),
            description: 'Staff',
        })
    })

    it('drops the id and both seeds of an experiment rule, keeping its holdout share', () => {
        const stored = { ...experiment(false, 50), id: 'rule-2', seed: 'rule-seed' } as FeatureFlagRulesV2DraftRule
        expect(
            duplicatedRule({ ...stored, holdout: { seed: 'holdout-seed', exclusion_percentage: 5 } } as any)
        ).toEqual({
            ...experiment(false, 50),
            holdout: { exclusion_percentage: 5 },
        })
    })
})
