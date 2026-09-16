import { BuiltLogic } from 'kea'
import { languages } from 'monaco-editor'

import type { codeEditorLogicType } from './codeEditorLogic'

export const hogQLMetadataProvider: () => languages.CodeActionProvider = () => ({
    provideCodeActions: (model, _range, context) => {
        const logic: BuiltLogic<codeEditorLogicType> | undefined = (model as any).codeEditorLogic
        if (logic?.isMounted()) {
            // The stored marker ranges describe the text the server analyzed. Monaco shifts the
            // markers it reports as the user types, but the stored ranges do not move, so applying
            // one would rewrite whatever now sits at the old position. Offer nothing until a report
            // for the current text is in.
            const analyzed = logic.values.metadata?.[0]
            const analyzedOffset = logic.props.metadataQueryOffset ?? 0
            if (
                logic.values.metadataLoading ||
                analyzed === undefined ||
                model.getValue().slice(analyzedOffset, analyzedOffset + analyzed.length) !== analyzed
            ) {
                return { actions: [], dispose: () => {} }
            }
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
                    // Compare document offsets on both sides. `rawMarker.start/end` index the metadata
                    // query, which is one statement of the script, so they only line up with Monaco's
                    // offsets in the first statement. The line/column range already carries the
                    // statement's offset.
                    const rawStart = model.getOffsetAt({
                        lineNumber: rawMarker.startLineNumber,
                        column: rawMarker.startColumn,
                    })
                    const rawEnd = model.getOffsetAt({
                        lineNumber: rawMarker.endLineNumber,
                        column: rawMarker.endColumn,
                    })
                    if (
                        rawMarker.hogQLFix &&
                        // if ranges overlap
                        rawStart <= end &&
                        rawEnd >= start
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
                                        // Monaco refuses the edit if the model changed after the
                                        // action was offered, which the checks above cannot cover.
                                        versionId: model.getVersionId(),
                                    },
                                ],
                            },
                            isPreferred: true,
                        })
                    }
                    if (
                        rawMarker.hogQLAIFixPrompt &&
                        // if ranges overlap
                        rawStart <= end &&
                        rawEnd >= start
                    ) {
                        quickFixes.push({
                            title: 'Fix with AI',
                            diagnostics: [rawMarker],
                            kind: 'quickfix',
                            command: {
                                id: 'posthog.hogql.fixWithAI',
                                title: 'Fix with AI',
                                arguments: [rawMarker.hogQLAIFixPrompt],
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
