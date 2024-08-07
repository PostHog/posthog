import './CodeEditor.scss'

import MonacoEditor, { type EditorProps, loader, Monaco } from '@monaco-editor/react'
import { BuiltLogic, useMountedLogic, useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { codeEditorLogic } from 'lib/monaco/codeEditorLogic'
import { codeEditorLogicType } from 'lib/monaco/codeEditorLogicType'
import { findNextFocusableElement, findPreviousFocusableElement } from 'lib/monaco/domUtils'
import { hogQLAutocompleteProvider } from 'lib/monaco/hogQLAutocompleteProvider'
import { hogQLMetadataProvider } from 'lib/monaco/hogQLMetadataProvider'
import * as hog from 'lib/monaco/languages/hog'
import * as hogJson from 'lib/monaco/languages/hogJson'
import * as hogQL from 'lib/monaco/languages/hogQL'
import * as hogTemplate from 'lib/monaco/languages/hogTemplate'
import { inStorybookTestRunner } from 'lib/utils'
import { editor, editor as importedEditor, IDisposable } from 'monaco-editor'
import * as monaco from 'monaco-editor'
import { useEffect, useMemo, useRef, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { AnyDataNode, HogLanguage } from '~/queries/schema'

if (loader) {
    loader.config({ monaco })
}

export interface CodeEditorProps extends Omit<EditorProps, 'loading' | 'theme'> {
    queryKey?: string
    autocompleteContext?: string
    onPressCmdEnter?: (value: string, selectionType: 'selection' | 'full') => void
    autoFocus?: boolean
    sourceQuery?: AnyDataNode
    globals?: Record<string, any>
    schema?: Record<string, any> | null
}
let codeEditorIndex = 0

function initEditor(
    monaco: Monaco,
    editor: importedEditor.IStandaloneCodeEditor,
    editorProps: Omit<CodeEditorProps, 'options' | 'onMount' | 'queryKey' | 'value'>,
    options: editor.IStandaloneEditorConstructionOptions,
    builtCodeEditorLogic: BuiltLogic<codeEditorLogicType>
): void {
    // This gives autocomplete access to the specific editor
    const model = editor.getModel()
    ;(model as any).codeEditorLogic = builtCodeEditorLogic

    if (editorProps?.language === 'hog') {
        if (!monaco.languages.getLanguages().some(({ id }) => id === 'hog')) {
            monaco.languages.register({ id: 'hog', extensions: ['.hog'], mimetypes: ['application/hog'] })
            monaco.languages.setLanguageConfiguration('hog', hog.conf())
            monaco.languages.setMonarchTokensProvider('hog', hog.language())
            monaco.languages.registerCompletionItemProvider('hog', hogQLAutocompleteProvider(HogLanguage.hog))
            monaco.languages.registerCodeActionProvider('hog', hogQLMetadataProvider())
        }
    }
    if (editorProps?.language === 'hogQL' || editorProps?.language === 'hogQLExpr') {
        const language: HogLanguage = editorProps.language as HogLanguage
        if (!monaco.languages.getLanguages().some(({ id }) => id === language)) {
            monaco.languages.register(
                language === 'hogQL'
                    ? {
                          id: language,
                          extensions: ['.sql', '.hogql'],
                          mimetypes: ['application/hogql'],
                      }
                    : {
                          id: language,
                          mimetypes: ['application/hogql+expr'],
                      }
            )
            monaco.languages.setLanguageConfiguration(language, hogQL.conf())
            monaco.languages.setMonarchTokensProvider(language, hogQL.language())
            monaco.languages.registerCompletionItemProvider(language, hogQLAutocompleteProvider(language))
            monaco.languages.registerCodeActionProvider(language, hogQLMetadataProvider())
        }
    }
    if (editorProps?.language === 'hogTemplate') {
        if (!monaco.languages.getLanguages().some(({ id }) => id === 'hogTemplate')) {
            monaco.languages.register({
                id: 'hogTemplate',
                mimetypes: ['application/hog+template'],
            })
            monaco.languages.setLanguageConfiguration('hogTemplate', hogTemplate.conf())
            monaco.languages.setMonarchTokensProvider('hogTemplate', hogTemplate.language())
            monaco.languages.registerCompletionItemProvider(
                'hogTemplate',
                hogQLAutocompleteProvider(HogLanguage.hogTemplate)
            )
            monaco.languages.registerCodeActionProvider('hogTemplate', hogQLMetadataProvider())
        }
    }
    if (editorProps?.language === 'hogJson') {
        if (!monaco.languages.getLanguages().some(({ id }) => id === 'hogJson')) {
            monaco.languages.register({
                id: 'hogJson',
                mimetypes: ['application/hog+json'],
            })
            monaco.languages.setLanguageConfiguration('hogJson', hogJson.conf())
            monaco.languages.setMonarchTokensProvider('hogJson', hogJson.language())
            monaco.languages.registerCompletionItemProvider('hogJson', hogQLAutocompleteProvider(HogLanguage.hogJson))
            monaco.languages.registerCodeActionProvider('hogJson', hogQLMetadataProvider())
        }
    }
    if (options.tabFocusMode) {
        editor.onKeyDown((evt) => {
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
    useEffect(() => {
        return () => {
            monacoRoot?.remove()
        }
    }, [])

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
    useEffect(() => {
        return () => {
            monacoDisposables.current.forEach((d) => d?.dispose())
        }
    }, [])

    return (
        <MonacoEditor // eslint-disable-line react/forbid-elements
            key={queryKey}
            theme={isDarkModeOn ? 'vs-dark' : 'vs-light'}
            loading={<Spinner />}
            options={{
                // :TRICKY: We need to declare all options here, as omitting something will carry its value from one <CodeEditor> to another.
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
            }}
            value={value}
            onMount={(editor, monaco) => {
                setMonacoAndEditor([monaco, editor])
                initEditor(monaco, editor, editorProps, options ?? {}, builtCodeEditorLogic)
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
            }}
            {...editorProps}
        />
    )
}
