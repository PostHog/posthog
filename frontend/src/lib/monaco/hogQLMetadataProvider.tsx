import { BuiltLogic } from 'kea'
import { languages } from 'monaco-editor'

import type { codeEditorLogicType } from './codeEditorLogic'

export const hogQLMetadataProvider: () => languages.CodeActionProvider = () => ({
    provideCodeActions: (model, range, context) => {
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
                                        versionId: undefined,
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
            // A query-level fix is offered from anywhere in its statement. Requiring the caret on the
            // marker hides it from a reader who is not looking at the flagged token.
            const caretOffset = model.getOffsetAt({
                lineNumber: range.startLineNumber,
                column: range.startColumn,
            })
            const seenEdits = new Set<string>()
            for (const rawMarker of markersFromMetadata) {
                const scope = rawMarker.hogQLFixScope
                if (!rawMarker.hogQLFixAction || !scope) {
                    continue
                }
                const scopeStart = model.getOffsetAt({
                    lineNumber: scope.startLineNumber,
                    column: scope.startColumn,
                })
                const scopeEnd = model.getOffsetAt({ lineNumber: scope.endLineNumber, column: scope.endColumn })
                if (caretOffset < scopeStart || caretOffset > scopeEnd) {
                    continue
                }
                const key = JSON.stringify(rawMarker.hogQLFixAction.edits)
                if (seenEdits.has(key)) {
                    continue
                }
                seenEdits.add(key)
                quickFixes.push({
                    title: rawMarker.hogQLFixAction.title,
                    diagnostics: [rawMarker],
                    kind: 'quickfix',
                    edit: {
                        edits: rawMarker.hogQLFixAction.edits.map((fixEdit) => ({
                            resource: model.uri,
                            textEdit: { range: fixEdit.range, text: fixEdit.text },
                            versionId: undefined,
                        })),
                    },
                    isPreferred: true,
                })
            }

            return {
                actions: quickFixes,
                dispose: () => {},
            }
        }
    },
})
