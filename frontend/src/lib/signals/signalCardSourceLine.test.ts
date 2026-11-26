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

    test.each([
        [{ 'signals-scout-apm': 'Checkout latency' }, 'Scout · Checkout latency'],
        [{}, 'Scout · APM'],
    ])('a scout finding prefers the name the team set: %o', (scoutNames, expected) => {
        const signal = {
            source_product: 'signals_scout',
            source_type: 'finding',
            extra: { skill_name: 'signals-scout-apm' },
        }
        expect(signalCardSourceLine(signal, scoutNames)).toBe(expected)
    })
})
