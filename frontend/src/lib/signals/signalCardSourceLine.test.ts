import { signalCardSourceLine } from './signalCardSourceLine'

describe('signalCardSourceLine', () => {
    test.each([
        ['a filed report reads as a team member', 'user_authored', 'cross_source_issue', undefined, 'Team member'],
        [
            'a scout finding names its scout',
            'signals_scout',
            'cross_source_issue',
            { skill_name: 'signals-scout-error-tracking' },
            'Scout · Error tracking',
        ],
        [
            'an unknown source falls back to its identifiers',
            'new_source',
            'some_type',
            undefined,
            'new source · some type',
        ],
    ])('%s', (_name, source_product, source_type, extra, expected) => {
        expect(signalCardSourceLine({ source_product, source_type, extra })).toBe(expected)
    })
})
