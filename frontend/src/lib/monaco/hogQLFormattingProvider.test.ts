import { editor, languages } from 'monaco-editor'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { hogQLFormattingProvider } from './hogQLFormattingProvider'

jest.mock('monaco-editor', () => ({ editor: { EndOfLinePreference: { LF: 1 } } }))
jest.mock('posthog-js')
jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { error: jest.fn() },
}))
jest.mock('./formatHogQL', () => {
    throw new Error('Failed to load the formatter')
})

describe('hogQLFormattingProvider', () => {
    it('keeps the query and shows a toast when the formatter does not load', async () => {
        const model = { getValue: () => 'select 1' } as unknown as editor.ITextModel
        const options = { tabSize: 4, insertSpaces: true } as languages.FormattingOptions

        const edits = await hogQLFormattingProvider().provideDocumentFormattingEdits(model, options, {} as any)

        expect(edits).toEqual([])
        expect(lemonToast.error).toHaveBeenCalledWith("Couldn't format this query. Try again in a moment.")
        expect(posthog.captureException).toHaveBeenCalled()
        expect(posthog.capture).toHaveBeenCalledWith(
            'sql-editor-query-formatted',
            expect.objectContaining({ succeeded: false, failure: 'unverified' })
        )
    })
})
