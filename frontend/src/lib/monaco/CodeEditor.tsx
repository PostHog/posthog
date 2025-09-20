import './CodeEditor.scss'

import MonacoEditor, { type EditorProps, Monaco, DiffEditor as MonacoDiffEditor, loader } from '@monaco-editor/react'
import { BuiltLogic, useMountedLogic, useValues } from 'kea'
import { IDisposable, editor, editor as importedEditor } from 'monaco-editor'
import * as monaco from 'monaco-editor'
import { useEffect, useMemo, useRef, useState } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { codeEditorLogic } from 'lib/monaco/codeEditorLogic'
import { codeEditorLogicType } from 'lib/monaco/codeEditorLogicType'
import { findNextFocusableElement, findPreviousFocusableElement } from 'lib/monaco/domUtils'
import { initHogLanguage } from 'lib/monaco/languages/hog'
import { initHogJsonLanguage } from 'lib/monaco/languages/hogJson'
import { initHogQLLanguage } from 'lib/monaco/languages/hogQL'
import { initHogTemplateLanguage } from 'lib/monaco/languages/hogTemplate'
import { initLiquidLanguage } from 'lib/monaco/languages/liquid'
import { inStorybookTestRunner } from 'lib/utils'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { AnyDataNode, HogLanguage, HogQLMetadataResponse, NodeKind } from '~/queries/schema/schema-general'

if (loader) {
    loader.config({ monaco })
}

export interface CodeEditorProps extends Omit<EditorProps, 'loading' | 'theme'> {
    queryKey?: string
    autocompleteContext?: string
    onPressCmdEnter?: (value: string, selectionType: 'selection' | 'full') => void
    /** Pressed up in an empty code editor, likely to edit the previous message in a list */
    onPressUpNoValue?: () => void
    autoFocus?: boolean
    sourceQuery?: AnyDataNode
    globals?: Record<string, any>
    schema?: Record<string, any> | null
    onMetadata?: (metadata: HogQLMetadataResponse | null) => void
    onMetadataLoading?: (loading: boolean) => void
    onError?: (error: string | null) => void
    /** The original value to compare against - renders it in diff mode */
    originalValue?: string
}
let codeEditorIndex = 0

export function initModel(model: editor.ITextModel, builtCodeEditorLogic: BuiltLogic<codeEditorLogicType>): void {
    ;(model as any).codeEditorLogic = builtCodeEditorLogic
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
    if (options.tabFocusMode || editorProps.onPressUpNoValue) {
        editor.onKeyDown((evt) => {
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
                if (
                    evt.keyCode === monaco.KeyCode.UpArrow &&
                    !evt.metaKey &&
                    !evt.ctrlKey &&
                    editor.getValue() === ''
                ) {
                    evt.preventDefault()
                    evt.stopPropagation()
                    editorProps.onPressUpNoValue()
                }
            }
        })
    }
}

export function CodeEditor({
    queryKey,
    options,
    onMount,
    value,
    onPressCmdEnter,
    autoFocus,
    globals,
    sourceQuery,
    schema,
    onError,
    onMetadata,
    onMetadataLoading,
    originalValue,
    ...editorProps
}: CodeEditorProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const scrollbarRendering = !inStorybookTestRunner() ? 'auto' : 'hidden'
    const [monacoAndEditor, setMonacoAndEditor] = useState(
        null as [Monaco, importedEditor.IStandaloneCodeEditor] | null
    )
    const [monaco, editor] = monacoAndEditor ?? []

    const [realKey] = useState(() => codeEditorIndex++)
    const builtCodeEditorLogic = codeEditorLogic({
        key: queryKey ?? `new/${realKey}`,
        query: value ?? '',
        language: editorProps.language ?? 'text',
        globals,
        sourceQuery,
        monaco: monaco,
        editor: editor,
        onError,
        onMetadata,
        onMetadataLoading,
        metadataFilters: sourceQuery?.kind === NodeKind.HogQLQuery ? sourceQuery.filters : undefined,
    })
    useMountedLogic(builtCodeEditorLogic)

    // Create DIV with .monaco-editor inside <body> for monaco's popups.
    // Without this monaco's tooltips will be mispositioned if inside another modal or popup.
    const monacoRoot = useMemo(() => {
        const body = (typeof document !== 'undefined' && document.getElementsByTagName('body')[0]) || null
        const monacoRoot = document.createElement('div')
        monacoRoot.classList.add('monaco-editor')
        monacoRoot.style.zIndex = 'var(--z-tooltip)'
        body?.appendChild(monacoRoot)
        return monacoRoot
    }, [])

    useOnMountEffect(() => {
        return () => monacoRoot?.remove()
    })

    useEffect(() => {
        if (!monaco) {
            return
        }
        monaco.languages.typescript.typescriptDefaults.setCompilerOptions({
            jsx: editorProps?.path?.endsWith('.tsx')
                ? monaco.languages.typescript.JsxEmit.React
                : monaco.languages.typescript.JsxEmit.Preserve,
            esModuleInterop: true,
        })
    }, [monaco, editorProps.path])

    useEffect(() => {
        if (!monaco) {
            return
        }
        monaco.languages.json.jsonDefaults.setDiagnosticsOptions({
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

    // Using useRef, not useState, as we don't want to reload the component when this changes.
    const monacoDisposables = useRef([] as IDisposable[])
    useOnMountEffect(() => {
        return () => {
            monacoDisposables.current.forEach((d) => d?.dispose())
        }
    })

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
        padding: { bottom: 8, top: 8 },
        scrollbar: {
            vertical: scrollbarRendering,
            horizontal: scrollbarRendering,
            ...options?.scrollbar,
        },
    }

    const editorOnMount = (editor: importedEditor.IStandaloneCodeEditor, monaco: Monaco): void => {
        setMonacoAndEditor([monaco, editor])
        initEditor(monaco, editor, editorProps, options ?? {}, builtCodeEditorLogic)

        // Override Monaco's suggestion widget styling to prevent truncation
        const overrideSuggestionWidgetStyling = (): void => {
            const style = document.createElement('style')
            style.textContent = `
            .monaco-editor .suggest-widget .monaco-list .monaco-list-row.string-label>.contents>.main>.left>.monaco-icon-label {
               flex-shrink: 0;
            }

            `
            document.head.appendChild(style)
        }

        // Apply styling immediately and also when suggestion widget appears
        overrideSuggestionWidgetStyling()

        // Monitor for suggestion widget creation and apply styling
        const observer = new MutationObserver(() => {
            const suggestWidget = document.querySelector('.monaco-editor .suggest-widget')
            if (suggestWidget) {
                overrideSuggestionWidgetStyling()
            }
        })
        observer.observe(document.body, { childList: true, subtree: true })

        // Clean up observer
        monacoDisposables.current.push({
            dispose: () => observer.disconnect(),
        })

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

    if (originalValue) {
        // If originalValue is provided, we render a diff editor instead
        const diffEditorOnMount = (diff: importedEditor.IStandaloneDiffEditor, monaco: Monaco): void => {
            const modifiedEditor = diff.getModifiedEditor()
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
        <MonacoEditor // eslint-disable-line react/forbid-elements
            key={queryKey}
            theme={isDarkModeOn ? 'vs-dark' : 'vs-light'}
            loading={<Spinner />}
            value={value}
            options={editorOptions}
            onMount={editorOnMount}
            {...editorProps}
        />
    )
}
