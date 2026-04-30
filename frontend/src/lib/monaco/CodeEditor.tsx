import './CodeEditor.scss'

import MonacoEditor, { type EditorProps, Monaco, DiffEditor as MonacoDiffEditor, loader } from '@monaco-editor/react'
import { BuiltLogic, useActions, useMountedLogic, useValues } from 'kea'
import * as monacoModule from 'monaco-editor'
import { IDisposable, editor, editor as importedEditor } from 'monaco-editor'
import { useEffect, useRef, useState } from 'react'

import 'lib/monaco/monacoEnvironment'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { codeEditorLogic } from 'lib/monaco/codeEditorLogic'
import { codeEditorLogicType } from 'lib/monaco/codeEditorLogicType'
import { findNextFocusableElement, findPreviousFocusableElement } from 'lib/monaco/domUtils'
import { initHogLanguage } from 'lib/monaco/languages/hog'
import { initHogJsonLanguage } from 'lib/monaco/languages/hogJson'
import { initHogQLLanguage } from 'lib/monaco/languages/hogQL'
import { initHogTemplateLanguage } from 'lib/monaco/languages/hogTemplate'
import { initLiquidLanguage } from 'lib/monaco/languages/liquid'
import { sharedMonacoOverflowRoot } from 'lib/monaco/sharedMonacoOverflowRoot'
import { inStorybookTestRunner } from 'lib/utils'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { AnyDataNode, HogLanguage, HogQLMetadataResponse, NodeKind } from '~/queries/schema/schema-general'

if (loader) {
    loader.config({ monaco: monacoModule })
}

export interface CodeEditorProps extends Omit<EditorProps, 'loading' | 'theme'> {
    queryKey?: string
    autocompleteContext?: string
    onPressCmdEnter?: (value: string, selectionType: 'selection' | 'full') => void
    /** Run the innermost subquery at cursor (Cmd+Shift+Enter) */
    onPressCmdShiftEnter?: () => void
    /** Pressed up in an empty code editor, likely to edit the previous message in a list */
    onPressUpNoValue?: () => void
    autoFocus?: boolean
    sourceQuery?: AnyDataNode
    globals?: Record<string, any>
    schema?: Record<string, any> | null
    onMetadata?: (metadata: HogQLMetadataResponse | null) => void
    onMetadataLoading?: (loading: boolean) => void
    onFixWithAI?: (prompt: string) => void
    onError?: (error: string | null) => void
    /** Override the query sent for metadata validation (e.g. active query in multi-query mode) */
    metadataQuery?: string
    /** Character offset of metadataQuery within the full editor text, for correct marker positioning */
    metadataQueryOffset?: number
    /** The original value to compare against - renders it in diff mode */
    originalValue?: string
    /** Enable vim keybindings */
    enableVimMode?: boolean
}
let codeEditorIndex = 0

export function initModel(model: editor.ITextModel, builtCodeEditorLogic: BuiltLogic<codeEditorLogicType>): void {
    ;(model as any).codeEditorLogic = builtCodeEditorLogic
}

export function clearLogicReference(model: editor.ITextModel): void {
    ;(model as any).codeEditorLogic = undefined
}

function initEditor(
    monaco: Monaco,
    editor: importedEditor.IStandaloneCodeEditor,
    editorProps: Omit<CodeEditorProps, 'options' | 'onMount' | 'queryKey' | 'value'>,
    options: editor.IStandaloneEditorConstructionOptions,
    builtCodeEditorLogic: BuiltLogic<codeEditorLogicType>
): void {
    // This gives autocomplete access to the specific editor
    const model = editor.getModel()
    if (model) {
        initModel(model, builtCodeEditorLogic)
    }

    if (editorProps?.language === 'hog') {
        initHogLanguage(monaco)
    }
    if (editorProps?.language === 'hogQL' || editorProps?.language === 'hogQLExpr') {
        initHogQLLanguage(monaco, editorProps.language as HogLanguage)
    }
    if (editorProps?.language === 'hogTemplate') {
        initHogTemplateLanguage(monaco)
    }
    if (editorProps?.language === 'hogJson') {
        initHogJsonLanguage(monaco)
    }
    if (editorProps?.language === 'liquid') {
        initLiquidLanguage(monaco)
    }

    editor.onKeyDown((evt) => {
        if (evt.keyCode === monaco.KeyCode.Space) {
            evt.stopPropagation()
        }

        if (options.tabFocusMode) {
            if (evt.keyCode === monaco.KeyCode.Tab && !evt.metaKey && !evt.ctrlKey) {
                const selection = editor.getSelection()
                if (
                    selection &&
                    (selection.startColumn !== selection.endColumn ||
                        selection.startLineNumber !== selection.endLineNumber)
                ) {
                    return
                }
                evt.preventDefault()
                evt.stopPropagation()

                const element: HTMLElement | null = evt.target?.parentElement?.parentElement?.parentElement ?? null
                if (!element) {
                    return
                }
                const nextElement = evt.shiftKey
                    ? findPreviousFocusableElement(element)
                    : findNextFocusableElement(element)

                if (nextElement && 'focus' in nextElement) {
                    nextElement.focus()
                }
            }
        }
        if (editorProps.onPressUpNoValue) {
            if (evt.keyCode === monaco.KeyCode.UpArrow && !evt.metaKey && !evt.ctrlKey && editor.getValue() === '') {
                evt.preventDefault()
                evt.stopPropagation()
                editorProps.onPressUpNoValue()
            }
        }
    })
}

export function CodeEditor({
    queryKey,
    options,
    onMount,
    value,
    onPressCmdEnter,
    onPressCmdShiftEnter,
    autoFocus,
    globals,
    sourceQuery,
    schema,
    onError,
    onMetadata,
    onMetadataLoading,
    onFixWithAI,
    metadataQuery,
    metadataQueryOffset,
    originalValue,
    enableVimMode,
    ...editorProps
}: CodeEditorProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const scrollbarRendering = !inStorybookTestRunner() ? 'auto' : 'hidden'
    const [monacoAndEditor, setMonacoAndEditor] = useState(
        null as [Monaco, importedEditor.IStandaloneCodeEditor] | null
    )
    const [monaco, editor] = monacoAndEditor ?? []

    // Keep a ref to the editor for cleanup - ensures we can dispose it even if state is stale
    const editorRef = useRef<importedEditor.IStandaloneCodeEditor | null>(null)
    // In diff mode editorRef holds the inner modified sub-editor; this
    // ref holds the parent diff editor so cleanup can dispose the whole
    // diff (original editor, diff widget, decorations, view zones).
    const diffEditorRef = useRef<importedEditor.IStandaloneDiffEditor | null>(null)

    const vimModeRef = useRef<{ dispose: () => void } | null>(null)
    const vimStatusBarRef = useRef<HTMLDivElement | null>(null)

    const [realKey] = useState(() => codeEditorIndex++)
    const builtCodeEditorLogic = codeEditorLogic({
        key: queryKey ?? `new/${realKey}`,
        query: value ?? '',
        metadataQuery: metadataQuery,
        metadataQueryOffset: metadataQueryOffset,
        language: editorProps.language ?? 'text',
        globals,
        sourceQuery,
        monaco: monaco,
        editor: editor,
        onError,
        onMetadata,
        onMetadataLoading,
        onFixWithAI,
        metadataFilters: sourceQuery?.kind === NodeKind.HogQLQuery ? sourceQuery.filters : undefined,
    })
    useMountedLogic(builtCodeEditorLogic)

    const { vimCommandHistory } = useValues(builtCodeEditorLogic)
    const { appendVimCommand } = useActions(builtCodeEditorLogic)

    const { isVisible } = usePageVisibility()

    const monacoRoot = sharedMonacoOverflowRoot()

    // Using useRef, not useState, as we don't want to reload the component when this changes.
    const monacoDisposables = useRef([] as IDisposable[])
    const mutationObserver = useRef<MutationObserver | null>(null)
    // Track every model this editor instance has been attached to, so we can
    // dispose them on unmount. Monaco models live in a global registry until
    // explicitly disposed; without this, models accumulate forever and retain
    // their attached `codeEditorLogic` BuiltLogic via `(model as any).codeEditorLogic`.
    const editorModelsRef = useRef<Set<editor.ITextModel>>(new Set())
    // Live ref to the Monaco API so the cleanup closure (captured by
    // `useOnMountEffect`'s [] dep) can read the *current* value rather than
    // the `null` it had at mount time. Without this the `stillInUse` guard
    // in `disposeTrackedModels` is dead code: `monaco.editor.getEditors()`
    // returns `[]` and every tracked model is unconditionally disposed.
    const monacoApiRef = useRef<Monaco | null>(null)

    const disposeMonacoDisposables = (): void => {
        monacoDisposables.current.forEach((d) => d?.dispose())
        monacoDisposables.current = []
    }

    const disconnectMutationObserver = (): void => {
        mutationObserver.current?.disconnect()
        mutationObserver.current = null
    }

    const disposeTrackedModels = (): void => {
        const models = editorModelsRef.current
        if (models.size === 0) {
            return
        }
        const monacoApi = monacoApiRef.current
        // Skip a model if any OTHER live editor still holds it as its current
        // model — disposing would break that editor, and nulling its
        // `codeEditorLogic` would silently break HogQL autocomplete /
        // metadata providers in the surviving editor.
        const otherEditors = (monacoApi?.editor.getEditors?.() ?? []).filter((e) => e !== editorRef.current)
        for (const model of models) {
            if (model.isDisposed()) {
                continue
            }
            const stillInUse = otherEditors.some((e) => e.getModel() === model)
            if (stillInUse) {
                continue
            }
            // Null the back-reference only on models we're actually about to
            // dispose. Doing it for shared models would break consumers
            // (e.g. hogQLAutocompleteProvider, hogQLMetadataProvider) that
            // read `model.codeEditorLogic` to look up logic state.
            clearLogicReference(model)
            try {
                model.dispose()
            } catch {
                // already disposed or in invalid state
            }
        }
        models.clear()
    }

    const trackEditorModels = (editorInstance: importedEditor.IStandaloneCodeEditor, monacoApi: Monaco): void => {
        monacoApiRef.current = monacoApi
        const initial = editorInstance.getModel()
        if (initial) {
            editorModelsRef.current.add(initial)
        }
        const disposable = editorInstance.onDidChangeModel((e) => {
            if (!e.newModelUrl) {
                return
            }
            const next = monacoApi.editor.getModel(e.newModelUrl)
            if (next) {
                editorModelsRef.current.add(next)
            }
        })
        monacoDisposables.current.push(disposable)
    }

    const disposeEditor = (): void => {
        try {
            if (diffEditorRef.current) {
                diffEditorRef.current.dispose()
            } else {
                editorRef.current?.dispose()
            }
        } catch {
            // already disposed
        }
        editorRef.current = null
        diffEditorRef.current = null
    }

    useOnMountEffect(() => {
        return () => {
            disposeMonacoDisposables()
            disconnectMutationObserver()

            // Dispose the editor BEFORE @monaco-editor/react's own cleanup
            // runs: Monaco's services (HoverService, ContextView,
            // DomListener) keep refs to the editor's container DOM that
            // survive the library's dispose. Disposing while we still hold
            // a strong reference lets Monaco tear down its services in an
            // order that releases those DOM refs.
            disposeEditor()

            // Now that our editor is disposed, dispose every model this
            // editor used and was uniquely owned by us. `disposeTrackedModels`
            // also nulls the `codeEditorLogic` back-reference on each
            // disposed model. Models still held by another live editor are
            // skipped on both counts, so HogQL autocomplete/metadata
            // providers (which read `model.codeEditorLogic`) keep working
            // for the surviving editor.
            disposeTrackedModels()

            setMonacoAndEditor(null)

            // Do NOT remove monacoRoot — it's a shared singleton that
            // Monaco's global services have permanent DomListeners on.
        }
    })

    useEffect(() => {
        if (!monaco) {
            return
        }
        monacoModule.typescript.typescriptDefaults.setCompilerOptions({
            jsx: editorProps?.path?.endsWith('.tsx')
                ? monacoModule.typescript.JsxEmit.React
                : monacoModule.typescript.JsxEmit.Preserve,
            esModuleInterop: true,
        })
    }, [monaco, editorProps.path])

    useEffect(() => {
        if (!monaco) {
            return
        }
        monacoModule.json.jsonDefaults.setDiagnosticsOptions({
            validate: true,
            schemas: schema
                ? [
                      {
                          uri: 'http://internal/node-schema.json',
                          fileMatch: ['*'],
                          schema: schema,
                      },
                  ]
                : [],
        })
    }, [monaco, schema])

    useEffect(() => {
        if (!editor) {
            return
        }

        let cancelled = false

        if (enableVimMode && vimStatusBarRef.current) {
            const statusBar = vimStatusBarRef.current
            void import('lib/monaco/vimMode').then(({ setupVimMode }) => {
                if (cancelled) {
                    return
                }
                vimModeRef.current = setupVimMode(editor, statusBar, {
                    initialHistory: vimCommandHistory,
                    onCommandExecuted: appendVimCommand,
                })
            })
        } else if (vimModeRef.current) {
            vimModeRef.current.dispose()
            vimModeRef.current = null
        }

        return () => {
            cancelled = true
            if (vimModeRef.current) {
                vimModeRef.current.dispose()
                vimModeRef.current = null
            }
        }
    }, [editor, enableVimMode, vimCommandHistory, appendVimCommand])

    const editorOptions: editor.IStandaloneEditorConstructionOptions = {
        minimap: {
            enabled: false,
        },
        scrollBeyondLastLine: false,
        automaticLayout: true,
        fixedOverflowWidgets: true,
        glyphMargin: false,
        folding: true,
        wordWrap: 'off',
        lineNumbers: 'on',
        tabFocusMode: false,
        overviewRulerBorder: true,
        hideCursorInOverviewRuler: false,
        overviewRulerLanes: 3,
        overflowWidgetsDomNode: monacoRoot,
        ...options,
        padding: { bottom: enableVimMode ? 28 : 8, top: 8 },
        scrollbar: {
            vertical: scrollbarRendering,
            horizontal: scrollbarRendering,
            alwaysConsumeMouseWheel: false,
            ...options?.scrollbar,
        },
    }

    const editorOnMount = (editor: importedEditor.IStandaloneCodeEditor, monaco: Monaco): void => {
        editorRef.current = editor
        trackEditorModels(editor, monaco)
        setMonacoAndEditor([monaco, editor])
        initEditor(monaco, editor, editorProps, options ?? {}, builtCodeEditorLogic)

        // Override Monaco's suggestion widget styling to prevent truncation
        const styleId = 'monaco-suggestion-widget-fix'
        const overrideSuggestionWidgetStyling = (): void => {
            // Only add style tag if it doesn't already exist
            if (!document.getElementById(styleId)) {
                const style = document.createElement('style')
                style.id = styleId
                style.textContent = `
                .monaco-editor .suggest-widget .monaco-list .monaco-list-row.string-label>.contents>.main>.left>.monaco-icon-label {
                   flex-shrink: 0;
                }
                `
                document.head.appendChild(style)
            }
        }

        // Apply styling immediately
        overrideSuggestionWidgetStyling()

        // Monitor for suggestion widget creation and apply styling
        const observer = new MutationObserver(() => {
            const suggestWidget = document.querySelector('.monaco-editor .suggest-widget')
            if (suggestWidget) {
                overrideSuggestionWidgetStyling()
            }
        })

        mutationObserver.current = observer
        observer.observe(document.body, { childList: true, subtree: true })

        // Clean up observers
        monacoDisposables.current.push({
            dispose: () => observer.disconnect(),
        })

        monacoDisposables.current.push(
            monaco.editor.registerCommand('posthog.hogql.fixWithAI', (_, prompt) => {
                if (typeof prompt === 'string' && prompt.length > 0) {
                    onFixWithAI?.(prompt)
                }
            })
        )

        if (onPressCmdEnter) {
            monacoDisposables.current.push(
                editor.addAction({
                    id: 'saveAndRunPostHog',
                    label: 'Save and run query',
                    keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter],
                    run: () => {
                        const selection = editor.getSelection()
                        const model = editor.getModel()
                        if (selection && model) {
                            const highlightedText = model.getValueInRange(selection)
                            onPressCmdEnter(highlightedText, 'selection')
                            return
                        }

                        onPressCmdEnter(editor.getValue(), 'full')
                    },
                })
            )
        }
        if (onPressCmdShiftEnter) {
            monacoDisposables.current.push(
                editor.addAction({
                    id: 'runSubqueryPostHog',
                    label: 'Run subquery at cursor',
                    keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.Enter],
                    run: () => {
                        onPressCmdShiftEnter()
                    },
                })
            )
        }
        if (autoFocus) {
            editor.focus()
            const model = editor.getModel()
            if (model) {
                editor.setPosition({
                    column: model.getLineContent(model.getLineCount()).length + 1,
                    lineNumber: model.getLineCount(),
                })
            }
        }

        onMount?.(editor, monaco)
    }

    useEffect(() => {
        if (!mutationObserver.current) {
            return
        }

        if (isVisible) {
            mutationObserver.current.observe(document.body, { childList: true, subtree: true })
        } else {
            mutationObserver.current.disconnect()
        }
    }, [isVisible])

    if (originalValue) {
        // If originalValue is provided, we render a diff editor instead
        const diffEditorOnMount = (diff: importedEditor.IStandaloneDiffEditor, monaco: Monaco): void => {
            const modifiedEditor = diff.getModifiedEditor()
            editorRef.current = modifiedEditor
            diffEditorRef.current = diff
            trackEditorModels(modifiedEditor, monaco)
            const original = diff.getOriginalEditor().getModel()
            if (original) {
                editorModelsRef.current.add(original)
            }
            setMonacoAndEditor([monaco, modifiedEditor])

            if (editorProps.onChange) {
                const disposable = modifiedEditor.onDidChangeModelContent((event: editor.IModelContentChangedEvent) => {
                    editorProps.onChange?.(modifiedEditor.getValue(), event)
                })
                monacoDisposables.current.push(disposable)
            }
            onMount?.(modifiedEditor, monaco)
        }

        return (
            <MonacoDiffEditor
                key={queryKey}
                loading={<Spinner />}
                theme={isDarkModeOn ? 'vs-dark' : 'vs-light'}
                original={originalValue}
                modified={value}
                options={{
                    ...editorOptions,
                    renderSideBySide: false,
                    acceptSuggestionOnEnter: 'on',
                    renderGutterMenu: false,
                }}
                onMount={diffEditorOnMount}
                {...editorProps}
            />
        )
    }

    return (
        <div className="CodeEditor relative h-full w-full">
            <MonacoEditor // eslint-disable-line react/forbid-elements
                key={queryKey}
                theme={isDarkModeOn ? 'vs-dark' : 'vs-light'}
                loading={<Spinner />}
                value={value}
                options={editorOptions}
                onMount={editorOnMount}
                {...editorProps}
            />
            {enableVimMode && (
                <div
                    ref={vimStatusBarRef}
                    className="CodeEditor__vim-status-bar absolute bottom-0 left-0 right-0 font-mono text-xs px-2 py-0.5 bg-bg-light border-t z-10"
                />
            )}
        </div>
    )
}
