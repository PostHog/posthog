import { cleanup, render, screen } from '@testing-library/react'

import { LoadFailure } from '../types'
import { TraceViewError } from './TraceViewError'

const CASES: [LoadFailure, string][] = [
    ['not_found', 'It may have been deleted, or it is outside the retention period.'],
    ['failed', 'Something went wrong while loading it. Try again in a moment.'],
]

describe('TraceViewError', () => {
    afterEach(() => {
        cleanup()
    })

    it.each(CASES)('explains a %s load', (loadFailure, message) => {
        render(<TraceViewError loadFailure={loadFailure} backLink={null} />)

        expect(screen.getByText(message)).toBeTruthy()
    })
})
