import { hogQLMetadataProvider } from 'lib/monaco/hogQLMetadataProvider'

import type { ModelMarker } from './codeEditorLogic'

describe('hogQLMetadataProvider', () => {
    // Two statements, so the second one's document offsets are far past its statement-relative ones.
    const SCRIPT = "select event from events;\nselect properties.foo from events where event = 'pageview'"
    const SECOND_STATEMENT_OFFSET = SCRIPT.indexOf('\n') + 1

    const lineStarts = (text: string): number[] => {
        const starts = [0]
        for (const line of text.split('\n')) {
            starts.push(starts[starts.length - 1] + line.length + 1)
        }
        return starts
    }

    const codeActionsAt = (markers: ModelMarker[], activeMarker: ModelMarker): languagesCodeAction[] => {
        const starts = lineStarts(SCRIPT)
        const model = {
            uri: 'inmemory://model/1',
            codeEditorLogic: { isMounted: () => true, values: { modelMarkers: markers } },
            getOffsetAt: ({ lineNumber, column }: { lineNumber: number; column: number }) =>
                starts[lineNumber - 1] + column - 1,
            getValue: () => SCRIPT,
        }
        const result = hogQLMetadataProvider().provideCodeActions?.(
            model as any,
            {} as any,
            { markers: [activeMarker], only: undefined, trigger: 1 } as any,
            {} as any
        )
        return ((result as any)?.actions ?? []) as languagesCodeAction[]
    }

    interface languagesCodeAction {
        title: string
    }

    // `event = 'pageview'` sits in the second statement. Its statement-relative offsets are small,
    // while its line and column point past the first statement.
    const taxonomyMarker = (): ModelMarker =>
        ({
            message: "Event 'pageview' was not found in this project taxonomy.",
            hogQLFix: "'$pageview'",
            // Relative to the second statement, which is what the metadata query covered.
            start: SCRIPT.indexOf("'pageview'") - SECOND_STATEMENT_OFFSET,
            end: SCRIPT.indexOf("'pageview'") - SECOND_STATEMENT_OFFSET + "'pageview'".length,
            startLineNumber: 2,
            startColumn: SCRIPT.indexOf("'pageview'") - SECOND_STATEMENT_OFFSET + 1,
            endLineNumber: 2,
            endColumn: SCRIPT.indexOf("'pageview'") - SECOND_STATEMENT_OFFSET + 1 + "'pageview'".length,
            severity: 4,
        }) as ModelMarker

    it('offers a quick fix for a marker in a statement after the first', () => {
        const marker = taxonomyMarker()

        const actions = codeActionsAt([marker], marker)

        expect(actions.map((action) => action.title)).toEqual(["Replace with: '$pageview'"])
    })

    it('does not offer a quick fix when the caret is on an unrelated marker', () => {
        const marker = taxonomyMarker()
        const elsewhere: ModelMarker = {
            ...marker,
            startLineNumber: 1,
            startColumn: 1,
            endLineNumber: 1,
            endColumn: 7,
        }

        const actions = codeActionsAt([marker], elsewhere)

        expect(actions).toEqual([])
    })
})
