import { useActions, useValues } from 'kea'
import { HogQLQuery } from '~/queries/schema'
import { useEffect, useRef, useState } from 'react'
import { hogQLQueryEditorLogic } from './hogQLQueryEditorLogic'
import { Monaco } from '@monaco-editor/react'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { IconAutoAwesome, IconInfo } from 'lib/lemon-ui/icons'
import { LemonInput, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import type { IDisposable, editor as importedEditor, languages } from 'monaco-editor'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CodeEditor } from 'lib/components/CodeEditors'
import clsx from 'clsx'

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
                className={clsx('flex flex-col rounded bg-bg-light space-y-2 w-full', !props.embedded && 'p-2 border')}
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
                    <span className="absolute top-0 right-0 mt-1 mr-1 z-10">
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
                            className="py-2 border rounded overflow-hidden h-full"
                            language="mysql"
                            value={queryInput}
                            onChange={(v) => setQueryInput(v ?? '')}
                            height="100%"
                            onMount={(editor, monaco) => {
                                monaco.languages.registerCodeActionProvider('mysql', {
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
                                })
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
                    {featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_VIEWS] ? (
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
                            {'Save as View'}
                        </LemonButton>
                    ) : null}
                    <LemonButtonWithDropdown
                        className="ml-2"
                        icon={<IconInfo />}
                        type="secondary"
                        size="small"
                        dropdown={{
                            overlay: (
                                <div>
                                    Save a query as a view that can be referenced in another query. This is useful for
                                    modeling data and organizing large queries into readable chunks.{' '}
                                    <Link to={'https://posthog.com/docs/data-warehouse'}>More Info</Link>{' '}
                                </div>
                            ),
                            placement: 'right-start',
                            fallbackPlacements: ['left-start'],
                            actionable: true,
                            closeParentPopoverOnClickInside: true,
                        }}
                    />
                </div>
            </div>
        </div>
    )
}
