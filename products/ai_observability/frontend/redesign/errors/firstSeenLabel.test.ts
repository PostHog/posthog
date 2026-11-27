import { firstSeenLabel } from './firstSeenLabel'

const TOOLTIP = 'Earliest activity since Aug 2, 2026. Nothing older was checked.'

describe('firstSeenLabel', () => {
    it.each([
        ['a first seen date', '2026-09-02T12:30:00Z', { text: 'Sep 2, 2026', tooltip: TOOLTIP }],
        ['no occurrence since the checked date', null, { text: '-', tooltip: TOOLTIP }],
    ])('labels %s with the checked date', (_name, firstSeen, expected) => {
        expect(firstSeenLabel(firstSeen, '2026-08-02')).toEqual(expected)
    })
})
