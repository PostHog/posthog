import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { CodeEditor } from './CodeEditor'

// The lazily-imported Monaco editor fails to load. This drives the facade's error boundary: without
// it a failed chunk load rethrows past a bare Suspense and renders nothing, leaving the editor an
// empty region. The boundary must instead show a recoverable message with a retry control.
jest.mock('./CodeEditorImpl', () => ({
    CodeEditor: () => {
        throw new Error('Importing a module script failed.')
    },
}))

jest.mock('posthog-js', () => ({ __esModule: true, default: { captureException: jest.fn() } }))

describe('CodeEditor', () => {
    beforeEach(() => {
        // React logs caught boundary errors to console.error; silence the expected noise.
        jest.spyOn(console, 'error').mockImplementation(() => {})
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('renders a recoverable error with a retry control when the editor chunk fails to load', async () => {
        render(<CodeEditor language="hogQL" value="" />)

        expect(await screen.findByText(/code editor failed to load/i)).toBeInTheDocument()
        expect(screen.getAllByText('Try again').length).toBeGreaterThan(0)
    })
})
