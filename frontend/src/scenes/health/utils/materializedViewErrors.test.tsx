import { render } from '@testing-library/react'

import { getErrorLabelForMaterializedView } from './materializedViewErrors'

describe('getErrorLabelForMaterializedView', () => {
    it('returns no help when there is no error', () => {
        expect(getErrorLabelForMaterializedView(null)).toBeNull()
    })

    it('returns no help for an error it does not recognize', () => {
        expect(getErrorLabelForMaterializedView('DB::Exception: some unmapped failure')).toBeNull()
    })

    it.each([
        ['resource limit', 'DB::Exception: Memory limit (total) exceeded', 'too much memory'],
        ['timeout', 'DB::Exception: Timeout exceeded: elapsed 30 s', 'timed out'],
        ['missing column', "DB::Exception: Unknown column 'amount'", 'column that no longer exists'],
        ['missing source', "DB::Exception: Table default.stripe_charges doesn't exist", 'source this view depends on'],
    ])('maps a %s error to actionable help', (_label, error, expectedText) => {
        const help = getErrorLabelForMaterializedView(error)
        expect(help).not.toBeNull()
        const { container } = render(help as JSX.Element)
        expect(container.textContent).toContain(expectedText)
    })
})
