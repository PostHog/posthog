import type { SignalReportAssignmentPrStateEnumApi } from 'products/signals/frontend/generated/api.schemas'
import { SignalReportStatus } from 'products/signals/frontend/inbox/types'

import { derivePrState, prCiGlyphStatus, type PrBadgeState } from './prState'

describe('prState', () => {
    describe('derivePrState', () => {
        const cases: [
            string,
            SignalReportStatus,
            boolean,
            SignalReportAssignmentPrStateEnumApi | null | undefined,
            PrBadgeState,
        ][] = [
            ['merged wins over every other state', SignalReportStatus.READY, true, 'draft', 'merged'],
            ['a terminal report has no open PR', SignalReportStatus.SUPPRESSED, false, 'open', 'closed'],
            ['a terminal report outranks a stale draft flag', SignalReportStatus.SUPPRESSED, false, 'draft', 'closed'],
            ['a draft PR is not up for review', SignalReportStatus.READY, false, 'draft', 'draft'],
            ['an open PR is up for review', SignalReportStatus.READY, false, 'open', 'open'],
            ['an unreported PR state reads as open', SignalReportStatus.READY, false, undefined, 'open'],
        ]

        test.each(cases)('%s', (_name, status, prMerged, prState, expected) => {
            expect(derivePrState(status, prMerged, prState)).toBe(expected)
        })
    })

    describe('prCiGlyphStatus', () => {
        // A glyph is a claim about work a reader can still act on. Claiming it for a landed pull
        // request, or claiming green when nothing answered, is worse than saying nothing.
        it.each([
            ['a failing open pull request', 'open', 'failing', 'failing'],
            ['a passing open pull request', 'open', 'passing', 'passing'],
            ['an open pull request mid-build', 'open', 'pending', 'pending'],
            ['a failing draft pull request', 'draft', 'failing', 'failing'],
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
