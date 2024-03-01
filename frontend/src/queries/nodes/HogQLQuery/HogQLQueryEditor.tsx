import { Monaco } from '@monaco-editor/react'
import { IconInfo } from '@posthog/icons'
import { LemonInput, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CodeEditor } from 'lib/components/CodeEditors'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconAutoAwesome } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { editor as importedEditor, IDisposable } from 'monaco-editor'
import { languages } from 'monaco-editor'
import { useEffect, useRef, useState } from 'react'
import { urls } from 'scenes/urls'

import { query } from '~/queries/query'
import { AutocompleteCompletionItem, HogQLAutocomplete, HogQLQuery, NodeKind } from '~/queries/schema'

import { hogQLQueryEditorLogic } from './hogQLQueryEditorLogic'

const convertCompletionItemKind = (kind: AutocompleteCompletionItem['kind']): languages.CompletionItemKind => {
    switch (kind) {
        case 'Method':
            return languages.CompletionItemKind.Method
        case 'Function':
            return languages.CompletionItemKind.Function
        case 'Constructor':
            return languages.CompletionItemKind.Constructor
        case 'Field':
            return languages.CompletionItemKind.Field
        case 'Variable':
            return languages.CompletionItemKind.Variable
        case 'Class':
            return languages.CompletionItemKind.Class
        case 'Struct':
            return languages.CompletionItemKind.Struct
        case 'Interface':
            return languages.CompletionItemKind.Interface
        case 'Module':
            return languages.CompletionItemKind.Module
        case 'Property':
            return languages.CompletionItemKind.Property
        case 'Event':
            return languages.CompletionItemKind.Event
        case 'Operator':
            return languages.CompletionItemKind.Operator
        case 'Unit':
            return languages.CompletionItemKind.Unit
        case 'Value':
            return languages.CompletionItemKind.Value
        case 'Constant':
            return languages.CompletionItemKind.Constant
        case 'Enum':
            return languages.CompletionItemKind.Enum
        case 'EnumMember':
            return languages.CompletionItemKind.EnumMember
        case 'Keyword':
            return languages.CompletionItemKind.Keyword
        case 'Text':
            return languages.CompletionItemKind.Text
        case 'Color':
            return languages.CompletionItemKind.Color
        case 'File':
            return languages.CompletionItemKind.File
        case 'Reference':
            return languages.CompletionItemKind.Reference
        case 'Customcolor':
            return languages.CompletionItemKind.Customcolor
        case 'Folder':
            return languages.CompletionItemKind.Folder
        case 'TypeParameter':
            return languages.CompletionItemKind.TypeParameter
        case 'User':
            return languages.CompletionItemKind.User
        case 'Issue':
            return languages.CompletionItemKind.Issue
        case 'Snippet':
            return languages.CompletionItemKind.Snippet
        default:
            throw new Error(`Unknown CompletionItemKind: ${kind}`)
    }
}

const kindToSortText = (kind: AutocompleteCompletionItem['kind'], label: string): string => {
    if (kind === 'Variable') {
        return `1-${label}`
    }
    if (kind === 'Method' || kind === 'Function') {
        return `2-${label}`
    }
    return `3-${label}`
}

export interface HogQLQueryEditorProps {
    query: HogQLQuery
    setQuery?: (query: HogQLQuery) => void
    embedded?: boolean
}

let uniqueNode = 0
export function HogQLQueryEditor(props: HogQLQueryEditorProps): JSX.Element {
    const [key] = useState(() => uniqueNode++)
    const [monacoAndEditor, setMonacoAndEditor] = useState(
        null as [Monaco, importedEditor.IStandaloneCodeEditor] | null
    )
    const [monaco, editor] = monacoAndEditor ?? []
    const hogQLQueryEditorLogicProps = { query: props.query, setQuery: props.setQuery, key, editor, monaco }
    const logic = hogQLQueryEditorLogic(hogQLQueryEditorLogicProps)
    const { queryInput, hasErrors, error, prompt, aiAvailable, promptError, promptLoading, isValidView } =
        useValues(logic)
    const { setQueryInput, saveQuery, setPrompt, draftFromPrompt, saveAsView } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Using useRef, not useState, as we don't want to reload the component when this changes.
    const monacoDisposables = useRef([] as IDisposable[])
    useEffect(() => {
        return () => {
            monacoDisposables.current.forEach((d) => d?.dispose())
        }
    }, [])

    return (
        <div className="space-y-2">
            <div
                data-attr="hogql-query-editor"
                className={clsx('flex flex-col rounded space-y-2 w-full', !props.embedded && 'p-2 border')}
            >
                <FlaggedFeature flag={FEATURE_FLAGS.ARTIFICIAL_HOG}>
                    <div className="flex gap-2">
                        <LemonInput
                            className="grow"
                            prefix={<IconAutoAwesome />}
                            value={prompt}
                            onPressEnter={() => draftFromPrompt()}
                            onChange={(value) => setPrompt(value)}
                            placeholder={
                                aiAvailable
                                    ? 'What do you want to know? How would you like to tweak the query?'
                                    : 'To use AI features, set environment variable OPENAI_API_KEY for this instance of PostHog'
                            }
                            disabled={!aiAvailable}
                            maxLength={400}
                        />
                        <LemonButton
                            type="primary"
                            onClick={() => draftFromPrompt()}
                            disabledReason={
                                !aiAvailable
                                    ? 'Environment variable OPENAI_API_KEY is unset for this instance of PostHog'
                                    : !prompt
                                    ? 'Provide a prompt first'
                                    : null
                            }
                            tooltipPlacement="left"
                            loading={promptLoading}
                        >
                            Think
                        </LemonButton>
                    </div>
                </FlaggedFeature>
                {promptError ? <LemonBanner type="warning">{promptError}</LemonBanner> : null}
                <div className="relative flex-1 overflow-hidden">
                    <span className="absolute top-0 right-0 mt-1 mr-5 z-10 bg-bg-light">
                        <LemonButtonWithDropdown
                            icon={<IconInfo />}
                            type="secondary"
                            size="small"
                            dropdown={{
                                overlay: (
                                    <div>
                                        Run SQL queries with{' '}
                                        <Link to="https://posthog.com/manual/hogql" target="_blank">
                                            HogQL
                                        </Link>
                                        , our wrapper around ClickHouse SQL. Explore the{' '}
                                        <Link
                                            to={
                                                featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE]
                                                    ? urls.dataWarehouse()
                                                    : urls.database()
                                            }
                                        >
                                            database schema
                                        </Link>{' '}
                                        available to you.
                                    </div>
                                ),
                                placement: 'right-start',
                                fallbackPlacements: ['left-start'],
                                actionable: true,
                                closeParentPopoverOnClickInside: true,
                            }}
                        />
                    </span>
                    {/* eslint-disable-next-line react/forbid-dom-props */}
                    <div className="resize-y overflow-hidden" style={{ height: 222 }}>
                        <CodeEditor
                            className="border rounded overflow-hidden h-full"
                            language="mysql"
                            value={queryInput}
                            onChange={(v) => setQueryInput(v ?? '')}
                            height="100%"
                            onMount={(editor, monaco) => {
                                const completetionItemProviderDisposable =
                                    monaco.languages.registerCompletionItemProvider('mysql', {
                                        triggerCharacters: [' ', ',', '.'],
                                        provideCompletionItems: async (model, position) => {
                                            if (!featureFlags[FEATURE_FLAGS.HOGQL_AUTOCOMPLETE]) {
                                                return undefined
                                            }

                                            const word = model.getWordUntilPosition(position)

                                            const startOffset = model.getOffsetAt({
                                                lineNumber: position.lineNumber,
                                                column: word.startColumn,
                                            })
                                            const endOffset = model.getOffsetAt({
                                                lineNumber: position.lineNumber,
                                                column: word.endColumn,
                                            })

                                            const response = await query<HogQLAutocomplete>({
                                                kind: NodeKind.HogQLAutocomplete,
                                                select: model.getValue(), // Use the text from the model instead of logic due to a race condition on the logic values updating quick enough
                                                filters: props.query.filters,
                                                startPosition: startOffset,
                                                endPosition: endOffset,
                                            })

                                            const completionItems = response.suggestions

                                            const suggestions = completionItems.map<languages.CompletionItem>(
                                                (item) => {
                                                    const kind = convertCompletionItemKind(item.kind)
                                                    const sortText = kindToSortText(item.kind, item.label)

                                                    return {
                                                        label: {
                                                            label: item.label,
                                                            detail: item.detail,
                                                        },
                                                        documentation: item.documentation,
                                                        insertText: item.insertText,
                                                        range: {
                                                            startLineNumber: position.lineNumber,
                                                            endLineNumber: position.lineNumber,
                                                            startColumn: word.startColumn,
                                                            endColumn: word.endColumn,
                                                        },
                                                        kind,
                                                        sortText,
                                                        command:
                                                            kind === languages.CompletionItemKind.Function
                                                                ? {
                                                                      id: 'cursorLeft',
                                                                      title: 'Move cursor left',
                                                                  }
                                                                : undefined,
                                                    }
                                                }
                                            )

                                            return {
                                                suggestions,
                                                incomplete: response.incomplete_list,
                                            }
                                        },
                                    })

                                monacoDisposables.current.push(completetionItemProviderDisposable)

                                const codeActionProviderDisposable = monaco.languages.registerCodeActionProvider(
                                    'mysql',
                                    {
                                        provideCodeActions: (model, _range, context) => {
                                            if (logic.isMounted()) {
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
                                    }
                                )
                                monacoDisposables.current.push(codeActionProviderDisposable)

                                monacoDisposables.current.push(
                                    editor.addAction({
                                        id: 'saveAndRunPostHog',
                                        label: 'Save and run query',
                                        keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter],
                                        run: () => saveQuery(),
                                    })
                                )
                                setMonacoAndEditor([monaco, editor])
                            }}
                            options={{
                                minimap: {
                                    enabled: false,
                                },
                                wordWrap: 'on',
                                scrollBeyondLastLine: false,
                                automaticLayout: true,
                                fixedOverflowWidgets: true,
                                suggest: {
                                    showInlineDetails: true,
                                },
                                quickSuggestionsDelay: 300,
                            }}
                        />
                    </div>
                </div>
                <div className="flex flex-row">
                    <div className="flex-1">
                        <LemonButton
                            onClick={saveQuery}
                            type="primary"
                            disabledReason={
                                !props.setQuery
                                    ? 'No permission to update'
                                    : hasErrors
                                    ? error ?? 'Query has errors'
                                    : undefined
                            }
                            center
                            fullWidth
                            data-attr="hogql-query-editor-save"
                        >
                            {!props.setQuery ? 'No permission to update' : 'Update and run'}
                        </LemonButton>
                    </div>
                    {featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE] ? (
                        <LemonButton
                            className="ml-2"
                            onClick={saveAsView}
                            type="primary"
                            center
                            disabledReason={
                                hasErrors
                                    ? error ?? 'Query has errors'
                                    : !isValidView
                                    ? 'All fields must have an alias'
                                    : ''
                            }
                            data-attr="hogql-query-editor-save-as-view"
                        >
                            Save as View
                        </LemonButton>
                    ) : null}
                    {featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE] && (
                        <LemonButtonWithDropdown
                            className="ml-2"
                            icon={<IconInfo />}
                            type="secondary"
                            size="small"
                            dropdown={{
                                overlay: (
                                    <div>
                                        Save a query as a view that can be referenced in another query. This is useful
                                        for modeling data and organizing large queries into readable chunks.{' '}
                                        <Link to="https://posthog.com/docs/data-warehouse">More Info</Link>{' '}
                                    </div>
                                ),
                                placement: 'right-start',
                                fallbackPlacements: ['left-start'],
                                actionable: true,
                                closeParentPopoverOnClickInside: true,
                            }}
                        />
                    )}
                </div>
            </div>
        </div>
    )
}
