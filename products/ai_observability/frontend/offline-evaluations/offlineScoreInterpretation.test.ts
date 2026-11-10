import { offlineScorePasses } from './offlineScoreInterpretation'

describe('offline score interpretation', () => {
    it.each<[Parameters<typeof offlineScorePasses>[1], unknown, boolean | null]>([
        [{ kind: 'boolean', config: {} }, true, true],
        [{ kind: 'boolean', config: { true_is_failure: null } }, false, false],
        [{ kind: 'boolean', config: { true_is_failure: false } }, true, true],
        [{ kind: 'boolean', config: { true_is_failure: false } }, false, false],
        [{ kind: 'boolean', config: { true_is_failure: true } }, true, false],
        [{ kind: 'boolean', config: { true_is_failure: true } }, false, true],
        [{ kind: 'boolean', config: { true_is_failure: false } }, 1, null],
        [{ kind: 'numeric', config: {} }, 1, null],
        [{ kind: 'categorical', config: { options: [] } }, ['good'], null],
        [
            { kind: 'categorical', config: { options: [], passing_rule: { categories: ['good', 'clear'] } } },
            ['good'],
            true,
        ],
        [
            { kind: 'categorical', config: { options: [], passing_rule: { categories: ['good', 'clear'] } } },
            ['good', 'clear'],
            true,
        ],
        [
            { kind: 'categorical', config: { options: [], passing_rule: { categories: ['good'] } } },
            ['good', 'bad'],
            false,
        ],
        [{ kind: 'categorical', config: { options: [], passing_rule: { categories: [] } } }, ['good'], false],

        [{ kind: 'numeric', config: { passing_rule: { operator: 'gte', threshold: 0 } } }, 0, true],
        [{ kind: 'numeric', config: { passing_rule: { operator: 'gte', threshold: 0 } } }, -1, false],
        [{ kind: 'numeric', config: { passing_rule: { operator: 'lte', threshold: 0 } } }, 0, true],
        [{ kind: 'numeric', config: { passing_rule: { operator: 'lte', threshold: 0 } } }, 1, false],
        [{ kind: 'numeric', config: { passing_rule: { operator: 'lte', threshold: 0 } } }, null, null],
        [{ kind: 'numeric', config: { passing_rule: { operator: 'lte', threshold: 0 } } }, NaN, null],
        [{ kind: 'numeric', config: { passing_rule: { operator: 'lte', threshold: Infinity } } }, 1, null],
    ])('interprets %j and value %p as %p', (scorer, value, expected) => {
        expect(offlineScorePasses(value, scorer)).toBe(expected)
    })
})
