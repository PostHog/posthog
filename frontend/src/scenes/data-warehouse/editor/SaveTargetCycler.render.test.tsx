import { render } from '@testing-library/react'
import { useState } from 'react'

import { SaveCandidates, SaveTargetCycler } from './SaveTargetCycler'

// candidates is stable across renders at every call site (a const in the dialog listener closure),
// so the harness keeps it stable and lets only onChange churn — the shape that caused the freeze.
const CANDIDATES: SaveCandidates = {
    queries: ['SELECT 1', 'SELECT 2'],
    initialIndex: 0,
    selectionLabel: null,
}

describe('SaveTargetCycler', () => {
    it('does not loop when the caller passes a new onChange every render', () => {
        // Mirrors the LemonField wiring: a fresh onChange closure each render whose call forces a
        // re-render. When the report effect depended on that identity, it re-ran on the render its
        // own write caused, feeding an infinite loop until React aborted with "Maximum update depth
        // exceeded". The counter guarantees each call re-renders, so a revived dependency loops here.
        const selected = jest.fn()

        function Harness(): JSX.Element {
            const [, forceRender] = useState(0)
            return (
                <SaveTargetCycler
                    candidates={CANDIDATES}
                    onChange={(query, index) => {
                        selected(query, index)
                        forceRender((n) => n + 1)
                    }}
                />
            )
        }

        expect(() => render(<Harness />)).not.toThrow()
        // The selection is reported for the initial index once, not stormed.
        expect(selected).toHaveBeenCalledTimes(1)
        expect(selected).toHaveBeenLastCalledWith('SELECT 1', 0)
    })
})
