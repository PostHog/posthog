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

    const MODEL_VERSION = 7

    const codeActionsAt = (
        markers: ModelMarker[],
        activeMarker: ModelMarker,
        { metadataLoading = false, modelText = SCRIPT }: { metadataLoading?: boolean; modelText?: string } = {}
    ): languagesCodeAction[] => {
        const starts = lineStarts(modelText)
        const model = {
            uri: 'inmemory://model/1',
            codeEditorLogic: {
                isMounted: () => true,
                props: { metadataQueryOffset: SECOND_STATEMENT_OFFSET },
                values: {
                    modelMarkers: markers,
                    metadataLoading,
                    // The metadata query covered the second statement.
                    metadata: [SCRIPT.slice(SECOND_STATEMENT_OFFSET), {}],
                },
            },
            getOffsetAt: ({ lineNumber, column }: { lineNumber: number; column: number }) =>
                starts[lineNumber - 1] + column - 1,
            getValue: () => modelText,
            getVersionId: () => MODEL_VERSION,
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
        edit?: { edits: { versionId?: number }[] }
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
        expect(actions[0].edit?.edits[0].versionId).toEqual(MODEL_VERSION)
    })

    // Typing before the analyzed statement shifts the text under the stored marker range, and a
    // refresh in flight means the stored ranges are about to be replaced. Either way the offered
    // edit would land on the wrong text.
    it.each([
        ['metadata is still loading', { metadataLoading: true }],
        ['the model text has moved on from the analyzed text', { modelText: ` ${SCRIPT}` }],
    ])('offers nothing when %s', (_, options) => {
        const marker = taxonomyMarker()

        const actions = codeActionsAt([marker], marker, options)

        expect(actions).toEqual([])
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
