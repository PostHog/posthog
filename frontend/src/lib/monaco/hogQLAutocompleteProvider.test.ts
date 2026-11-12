import type { languages } from 'monaco-editor'

import { hogQLAutocompleteProvider } from 'lib/monaco/hogQLAutocompleteProvider'

import { performQuery } from '~/queries/query'
import { HogLanguage } from '~/queries/schema/schema-general'

jest.mock('monaco-editor', () => ({
    languages: { CompletionItemKind: { Method: 0, Function: 1 } },
}))

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

describe('hogQLAutocompleteProvider', () => {
    beforeEach(() => {
        jest.mocked(performQuery).mockReset()
    })

    const completeAt = async (
        text: string,
        position: { lineNumber: number; column: number },
        word: { word: string; startColumn: number; endColumn: number }
    ): Promise<languages.CompletionList | null | undefined> => {
        const lineStarts = [0]
        for (const line of text.split('\n')) {
            lineStarts.push(lineStarts[lineStarts.length - 1] + line.length + 1)
        }
        const model = {
            codeEditorLogic: { isMounted: () => true, props: {} },
            getOffsetAt: ({ lineNumber, column }: { lineNumber: number; column: number }) =>
                lineStarts[lineNumber - 1] + column - 1,
            getValue: () => text,
            getWordUntilPosition: () => word,
        }

        return await hogQLAutocompleteProvider(HogLanguage.hogQL).provideCompletionItems?.(
            model as any,
            position as any,
            {} as any,
            {} as any
        )
    }

    it('exposes the complete function signature in suggestion details without changing insertion', async () => {
        jest.mocked(performQuery).mockResolvedValueOnce({
            suggestions: [
                {
                    label: 'quantileExactWeighted',
                    detail: '(level)(value, weight)',
                    kind: 'Function',
                    insertText: 'quantileExactWeighted()',
                    documentation: 'Calculate an exact weighted quantile.',
                },
            ],
            incomplete_list: false,
        })
        const result = await completeAt(
            'SELECT quant',
            { lineNumber: 1, column: 13 },
            {
                word: 'quant',
                startColumn: 8,
                endColumn: 13,
            }
        )
        expect(result?.suggestions[0]).toEqual(
            expect.objectContaining({
                detail: 'quantileExactWeighted(level)(value, weight)',
                insertText: 'quantileExactWeighted()',
            })
        )
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

    it('sends only the statement under the cursor when the document holds several queries', async () => {
        jest.mocked(performQuery).mockResolvedValueOnce({ suggestions: [], incomplete_list: false })
        await completeAt(
            'select 1;\nselect e',
            { lineNumber: 2, column: 9 },
            { word: 'e', startColumn: 8, endColumn: 9 }
        )

        expect(performQuery).toHaveBeenCalledWith(
            expect.objectContaining({
                query: '\nselect e',
                startPosition: 8,
                endPosition: 9,
            })
        )
    })

    it('keeps the statement scoped when the cursor rests on trailing whitespace', async () => {
        jest.mocked(performQuery).mockResolvedValueOnce({ suggestions: [], incomplete_list: false })

        // ' ' is a trigger character, so this fires on every space typed mid-statement.
        await completeAt(
            'select 1;\nselect e ',
            { lineNumber: 2, column: 10 },
            {
                word: '',
                startColumn: 10,
                endColumn: 10,
            }
        )

        expect(performQuery).toHaveBeenCalledWith(
            expect.objectContaining({
                query: '\nselect e ',
                startPosition: 10,
                endPosition: 10,
            })
        )
    })
})
