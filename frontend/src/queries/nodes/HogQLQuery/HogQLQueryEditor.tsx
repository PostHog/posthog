import { Monaco } from '@monaco-editor/react'
import { IconInfo, IconMagicWand } from '@posthog/icons'
import { LemonInput, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { codeEditorLogic } from 'lib/monaco/codeEditorLogic'
import type { editor as importedEditor, IDisposable } from 'monaco-editor'
import { useEffect, useRef, useState } from 'react'
import { DatabaseTableTreeWithItems } from 'scenes/data-warehouse/external/DataWarehouseTables'
import useResizeObserver from 'use-resize-observer'

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
const TABLE_PANEL_HEIGHT = EDITOR_HEIGHT + 78

export function HogQLQueryEditor(props: HogQLQueryEditorProps): JSX.Element {
    const editorRef = useRef<HTMLDivElement | null>(null)
    const { featureFlags } = useValues(featureFlagLogic)
    const artificialHogHeight = featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG] ? 40 : 0
    const [panelHeight, setPanelHeight] = useState<number>(TABLE_PANEL_HEIGHT + artificialHogHeight)

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
    const { queryInput, hasErrors, error, prompt, aiAvailable, promptError, promptLoading, isValidView } =
        useValues(logic)
    const { setQueryInput, saveQuery, setPrompt, draftFromPrompt, saveAsView } = useActions(logic)

    const codeEditorKey = `hogQLQueryEditor/${key}`
    const codeEditorLogicProps = {
        key: codeEditorKey,
        query: queryInput,
        language: 'hogql',
        metadataFilters: props.query.filters,
    }
    useMountedLogic(codeEditorLogic(codeEditorLogicProps))

    // Using useRef, not useState, as we don't want to reload the component when this changes.
    const monacoDisposables = useRef([] as IDisposable[])
    useEffect(() => {
        return () => {
            monacoDisposables.current.forEach((d) => d?.dispose())
        }
    }, [])

    useResizeObserver({
        ref: editorRef,
        onResize: () => {
            if (editorRef.current) {
                setPanelHeight(Math.max(TABLE_PANEL_HEIGHT, editorRef.current.clientHeight + 78 + artificialHogHeight))
            }
        },
    })

    return (
        <div className="flex items-start gap-2">
            <FlaggedFeature flag={FEATURE_FLAGS.DATA_WAREHOUSE}>
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div className="flex max-sm:hidden" style={{ maxHeight: panelHeight }}>
                    <DatabaseTableTreeWithItems inline />
                </div>
            </FlaggedFeature>
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
                            language="hogql"
                            value={queryInput}
                            onChange={(v) => setQueryInput(v ?? '')}
                            height="100%"
                            onMount={(editor, monaco) => {
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
                    {props.editorFooter ? (
                        props.editorFooter(hasErrors, error, isValidView)
                    ) : (
                        <>
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
                                    Save as view
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
                                                Save a query as a view that can be referenced in another query. This is
                                                useful for modeling data and organizing large queries into readable
                                                chunks.{' '}
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
                        </>
                    )}
                </div>
            </div>
        </div>
    )
}
