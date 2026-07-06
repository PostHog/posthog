import { hogQLAutocompleteProvider } from 'lib/monaco/hogQLAutocompleteProvider'

import { performQuery } from '~/queries/query'
import { HogLanguage } from '~/queries/schema/schema-general'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

describe('hogQLAutocompleteProvider', () => {
    beforeEach(() => {
        jest.mocked(performQuery).mockReset()
    })

    it('returns an empty completion list when the autocomplete query fails', async () => {
        jest.mocked(performQuery).mockRejectedValueOnce(new Error("trailing tokens after expression: 'is'"))
        const provider = hogQLAutocompleteProvider(HogLanguage.hogQL)
        const model = {
            codeEditorLogic: {
                isMounted: () => true,
                props: {},
            },
            getOffsetAt: ({ column }: { column: number }) => column - 1,
            getValue: () => 'select event is',
            getWordUntilPosition: () => ({
                word: 'is',
                startColumn: 14,
                endColumn: 16,
            }),
        }

        const result = await provider.provideCompletionItems?.(
            model as any,
            { lineNumber: 1, column: 16 } as any,
            {} as any,
            {} as any
        )

        expect(result).toEqual({
            suggestions: [],
            incomplete: false,
        })
        expect(performQuery).toHaveBeenCalledTimes(1)
    })
})
