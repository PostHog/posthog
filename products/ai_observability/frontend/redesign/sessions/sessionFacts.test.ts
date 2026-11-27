import { sessionFacts } from './sessionFacts'
import { makeSessionListItem } from './testFixtures'

describe('sessionFacts', () => {
    const totals = makeSessionListItem().totals

    test.each([
        ['every fact', {}, ['6 turns', '27m', '$0.0126']],
        ['one turn', { turnCount: 1 }, ['1 turn', '27m', '$0.0126']],
        ['no duration', { durationMs: null }, ['6 turns', '$0.0126']],
        ['no cost', { totals: { ...totals, costUsd: null } }, ['6 turns', '27m']],
        ['a cost of zero', { totals: { ...totals, costUsd: 0 } }, ['6 turns', '27m', '$0']],
    ])('lists %s', (_name, overrides, facts) => {
        expect(sessionFacts(makeSessionListItem(overrides))).toEqual(facts)
    })
})
