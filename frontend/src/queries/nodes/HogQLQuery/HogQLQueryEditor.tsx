import { Monaco } from '@monaco-editor/react'
import { IconInfo, IconMagicWand } from '@posthog/icons'
import { LemonInput, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { codeEditorLogic } from 'lib/monaco/codeEditorLogic'
import type { editor as importedEditor, IDisposable } from 'monaco-editor'
import { useEffect, useRef, useState } from 'react'
import { dataWarehouseSceneLogic } from 'scenes/data-warehouse/external/dataWarehouseSceneLogic'

import { HogQLQuery } from '~/queries/schema'

import { hogQLQueryEditorLogic } from './hogQLQueryEditorLogic'

export interface HogQLQueryEditorProps {
    query: HogQLQuery
    setQuery?: (query: HogQLQuery) => void
    onChange?: (query: string) => void
    embedded?: boolean
    editorFooter?: (hasErrors: boolean, errors: string | null, isValidView: boolean) => JSX.Element
}

let uniqueNode = 0

const EDITOR_HEIGHT = 222

export function HogQLQueryEditor(props: HogQLQueryEditorProps): JSX.Element {
    const editorRef = useRef<HTMLDivElement | null>(null)

    const [key] = useState(() => uniqueNode++)
    const [monacoAndEditor, setMonacoAndEditor] = useState(
        null as [Monaco, importedEditor.IStandaloneCodeEditor] | null
    )
    const [monaco, editor] = monacoAndEditor ?? []
    const hogQLQueryEditorLogicProps = {
        query: props.query,
        setQuery: props.setQuery,
        onChange: props.onChange,
        key,
        editor,
        monaco,
    }
    const logic = hogQLQueryEditorLogic(hogQLQueryEditorLogicProps)
    const { queryInput, prompt, aiAvailable, promptError, promptLoading } = useValues(logic)
    const { setQueryInput, saveQuery, setPrompt, draftFromPrompt, saveAsView, onUpdateView } = useActions(logic)

    const codeEditorKey = `hogQLQueryEditor/${key}`
    const codeEditorLogicProps = {
        key: codeEditorKey,
        query: queryInput,
        language: 'hogQL',
        metadataFilters: props.query.filters,
    }
    const { hasErrors, error, isValidView } = useValues(codeEditorLogic(codeEditorLogicProps))

    const { editingView } = useValues(dataWarehouseSceneLogic)
    // Using useRef, not useState, as we don't want to reload the component when this changes.
    const monacoDisposables = useRef([] as IDisposable[])
    useEffect(() => {
        return () => {
            monacoDisposables.current.forEach((d) => d?.dispose())
        }
    }, [])

    return (
        <div className="flex items-start gap-2">
            <div
                data-attr="hogql-query-editor"
                className={clsx(
                    'flex flex-col rounded space-y-2 w-full overflow-hidden',
                    !props.embedded && 'p-2 border'
                )}
            >
                <FlaggedFeature flag={FEATURE_FLAGS.ARTIFICIAL_HOG}>
                    <div className="flex gap-2">
                        <LemonInput
                            className="grow"
                            prefix={<IconMagicWand />}
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
                                        , our wrapper around ClickHouse SQL
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
                    <div ref={editorRef} className="resize-y overflow-hidden" style={{ height: EDITOR_HEIGHT }}>
                        <CodeEditor
                            queryKey={codeEditorKey}
                            className="border rounded overflow-hidden h-full"
                            language="hogQL"
                            value={queryInput}
                            onChange={(v) => setQueryInput(v ?? '')}
                            height="100%"
                            onMount={(editor, monaco) => {
                                setMonacoAndEditor([monaco, editor])
                            }}
                            onPressCmdEnter={(value, selectionType) => {
                                if (value && selectionType === 'selection') {
                                    saveQuery(value)
                                } else {
                                    saveQuery()
                                }
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
                    {props.editorFooter ? (
                        props.editorFooter(hasErrors, error, isValidView)
                    ) : (
                        <>
                            <div className="flex-1">
                                <LemonButton
                                    onClick={() => saveQuery()}
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
                            {editingView ? (
                                <LemonButton
                                    className="ml-2"
                                    onClick={onUpdateView}
                                    type="primary"
                                    center
                                    disabledReason={
                                        hasErrors
                                            ? error ?? 'Query has errors'
                                            : !isValidView
                                            ? 'All fields must have an alias'
                                            : ''
                                    }
                                    data-attr="hogql-query-editor-update-view"
                                >
                                    Update view
                                </LemonButton>
                            ) : (
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
                                    tooltip={
                                        <div>
                                            Save a query as a view that can be referenced in another query. This is
                                            useful for modeling data and organizing large queries into readable chunks.{' '}
                                            <Link to="https://posthog.com/docs/data-warehouse">More Info</Link>{' '}
                                        </div>
                                    }
                                >
                                    Save as view
                                </LemonButton>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>
    )
}
