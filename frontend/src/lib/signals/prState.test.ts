import { SignalReportStatus } from 'products/signals/frontend/inbox/types'

import { derivePrState, prCiGlyphStatus } from './prState'

describe('prState', () => {
    describe('prCiGlyphStatus', () => {
        // A glyph is a claim about work a reader can still act on. Claiming it for a landed pull
        // request, or claiming green when nothing answered, is worse than saying nothing.
        it.each([
            ['a failing open pull request', 'open', 'failing', 'failing'],
            ['a passing open pull request', 'open', 'passing', 'passing'],
            ['an open pull request mid-build', 'open', 'pending', 'pending'],
            ['a head commit with no checks', 'open', 'none', null],
            ['a status nothing has answered with', 'open', undefined, null],
            ['a merged pull request', 'merged', 'failing', null],
            ['a closed pull request', 'closed', 'failing', null],
        ] as const)('shows %s as %s', (_case, state, ciStatus, expected) => {
            expect(prCiGlyphStatus(state, ciStatus)).toBe(expected)
        })

        it('never glyphs a pull request the report has moved past', () => {
            // The two derivations have to agree: a resolved report's pill reads "closed", so the CI
            // state its report still carries must not paint it.
            const state = derivePrState(SignalReportStatus.RESOLVED, false)
            expect(prCiGlyphStatus(state, 'failing')).toBeNull()
        })
    })
})
