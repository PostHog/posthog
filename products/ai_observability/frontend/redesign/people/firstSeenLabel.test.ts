import { firstSeenLabel } from './firstSeenLabel'

const TOOLTIP = 'Earliest activity since Oct 26, 2026. Nothing older was checked.'

describe('firstSeenLabel', () => {
    it.each([
        ['a first seen date', '2026-11-12T12:30:00Z', { text: 'Nov 12, 2026', tooltip: TOOLTIP }],
        ['no activity since the checked date', null, { text: '-', tooltip: TOOLTIP }],
    ])('labels %s with the checked date', (_name, firstSeen, expected) => {
        expect(firstSeenLabel(firstSeen, '2026-10-26')).toEqual(expected)
    })
})
