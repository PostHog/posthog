import { BuiltLogic } from 'kea'
import { languages } from 'monaco-editor'

import type { codeEditorLogicType } from './codeEditorLogicType'

export const hogQLMetadataProvider: () => languages.CodeActionProvider = () => ({
    provideCodeActions: (model, _range, context) => {
        const logic: BuiltLogic<codeEditorLogicType> | undefined = (model as any).codeEditorLogic
        if (logic?.isMounted()) {
            // Monaco gives us a list of markers that we're looking at, but without the quick fixes.
            const markersFromMonaco = context.markers
            // We have a list of _all_ markers returned from the HogQL metadata query
            const markersFromMetadata = logic.values.modelMarkers
            // We need to merge the two lists
            const quickFixes: languages.CodeAction[] = []

            for (const activeMarker of markersFromMonaco) {
                const start = model.getOffsetAt({
                    column: activeMarker.startColumn,
                    lineNumber: activeMarker.startLineNumber,
                })
                const end = model.getOffsetAt({
                    column: activeMarker.endColumn,
                    lineNumber: activeMarker.endLineNumber,
                })
                for (const rawMarker of markersFromMetadata) {
                    if (
                        rawMarker.hogQLFix &&
                        // if ranges overlap
                        rawMarker.start <= end &&
                        rawMarker.end >= start
                    ) {
                        quickFixes.push({
                            title: `Replace with: ${rawMarker.hogQLFix}`,
                            diagnostics: [rawMarker],
                            kind: 'quickfix',
                            edit: {
                                edits: [
                                    {
                                        resource: model.uri,
                                        textEdit: {
                                            range: rawMarker,
                                            text: rawMarker.hogQLFix,
                                        },
                                        versionId: undefined,
                                    },
                                ],
                            },
                            isPreferred: true,
                        })
                    }
                }
            }
            return {
                actions: quickFixes,
                dispose: () => {},
            }
        }
    },
})
