import { useActions, useValues } from 'kea'
import { HogQLQuery } from '~/queries/schema'
import { useEffect, useRef, useState } from 'react'
import { hogQLQueryEditorLogic } from './hogQLQueryEditorLogic'
import MonacoEditor, { Monaco } from '@monaco-editor/react'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconAutoAwesome, IconInfo } from 'lib/lemon-ui/icons'
import { LemonInput, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import type { IDisposable, editor as importedEditor, languages } from 'monaco-editor'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export interface HogQLQueryEditorProps {
    query: HogQLQuery
    setQuery?: (query: HogQLQuery) => void
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
    const { queryInput, hasErrors, error, prompt, aiAvailable, promptError, promptLoading } = useValues(logic)
    const { setQueryInput, saveQuery, setPrompt, draftFromPrompt } = useActions(logic)
    const { isDarkModeOn } = useValues(themeLogic)
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
                className={'flex flex-col p-2 border rounded bg-bg-light space-y-2 resize-y w-full overflow-hidden'}
                style={{ height: 318 }}
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
                                        <a href="https://posthog.com/manual/hogql" target={'_blank'}>
                                            HogQL
                                        </a>
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
                    <MonacoEditor
                        theme={isDarkModeOn ? 'vs-dark' : 'light'}
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
                        loading={<Spinner />}
                    />
                </div>
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
                    fullWidth
                    center
                    data-attr="hogql-query-editor-save"
                >
                    {!props.setQuery ? 'No permission to update' : 'Update and run'}
                </LemonButton>
            </div>
        </div>
    )
}
