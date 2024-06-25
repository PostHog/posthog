import './CodeEditor.scss'

import MonacoEditor, { type EditorProps, Monaco } from '@monaco-editor/react'
import { BuiltLogic, useMountedLogic, useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { codeEditorLogic } from 'lib/monaco/codeEditorLogic'
import { codeEditorLogicType } from 'lib/monaco/codeEditorLogicType'
import { findNextFocusableElement, findPreviousFocusableElement } from 'lib/monaco/domUtils'
import { hogQLAutocompleteProvider } from 'lib/monaco/hogQLAutocompleteProvider'
import { hogQLMetadataProvider } from 'lib/monaco/hogQLMetadataProvider'
import * as hog from 'lib/monaco/languages/hog'
import * as hogQL from 'lib/monaco/languages/hogQL'
import * as hogTemplate from 'lib/monaco/languages/hogTemplate'
import { inStorybookTestRunner } from 'lib/utils'
import { editor, editor as importedEditor, IDisposable } from 'monaco-editor'
import { useEffect, useRef, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export interface CodeEditorProps extends Omit<EditorProps, 'loading' | 'theme'> {
    queryKey?: string
    autocompleteContext?: string
}
let codeEditorIndex = 0

function initEditor(
    monaco: Monaco,
    editor: importedEditor.IStandaloneCodeEditor,
    editorProps: Omit<CodeEditorProps, 'options' | 'onMount' | 'queryKey' | 'value'>,
    options: editor.IStandaloneEditorConstructionOptions,
    _monacoDisposables: React.MutableRefObject<IDisposable[]>,
    builtCodeEditorLogic: BuiltLogic<codeEditorLogicType>
): void {
    // This gives autocomplete access to the specific editor
    const model = editor.getModel()
    ;(model as any).codeEditorLogic = builtCodeEditorLogic

    if (editorProps?.language === 'hog') {
        if (!monaco.languages.getLanguages().some(({ id }) => id === 'hog')) {
            monaco.languages.register({ id: 'hog', extensions: ['.hog'], mimetypes: ['application/hog'] })
            monaco.languages.setLanguageConfiguration('hog', hog.conf)
            monaco.languages.setMonarchTokensProvider('hog', hog.language)
            monaco.languages.registerCodeActionProvider('hog', hogQLMetadataProvider())
        }
        // monacoDisposables.current.push(monaco.languages.registerCodeActionProvider('hog', hogQLMetadataProvider()))
    }
    if (editorProps?.language === 'hogQL' || editorProps?.language === 'hogExpr') {
        const language: 'hogQL' | 'hogExpr' = editorProps.language
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
            monaco.languages.setLanguageConfiguration(language, hogQL.conf)
            monaco.languages.setMonarchTokensProvider(language, hogQL.language)
            monaco.languages.registerCompletionItemProvider(language, hogQLAutocompleteProvider(language))
            monaco.languages.registerCodeActionProvider(language, hogQLMetadataProvider())
        }
        // monacoDisposables.current.push(monaco.languages.registerCodeActionProvider(language, hogQLMetadataProvider()))
    }
    if (editorProps?.language === 'hogTemplate') {
        if (!monaco.languages.getLanguages().some(({ id }) => id === 'hogTemplate')) {
            monaco.languages.register({
                id: 'hogTemplate',
                mimetypes: ['application/hog+template'],
            })
            monaco.languages.setLanguageConfiguration('hogTemplate', hogTemplate.conf)
            monaco.languages.setMonarchTokensProvider('hogTemplate', hogTemplate.language)
            monaco.languages.registerCompletionItemProvider('hogTemplate', hogQLAutocompleteProvider('hogTemplate'))
            monaco.languages.registerCodeActionProvider('hogTemplate', hogQLMetadataProvider())
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

export function CodeEditor({ queryKey, options, onMount, value, ...editorProps }: CodeEditorProps): JSX.Element {
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
        language: editorProps.language,
        monaco: monaco,
        editor: editor,
    })
    useMountedLogic(builtCodeEditorLogic)

    // Using useRef, not useState, as we don't want to reload the component when this changes.
    const monacoDisposables = useRef([] as IDisposable[])
    useEffect(() => {
        return () => {
            monacoDisposables.current.forEach((d) => d?.dispose())
        }
    }, [])

    return (
        <MonacoEditor // eslint-disable-line react/forbid-elements
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
                ...options,
                padding: { bottom: 8, top: 8 },
                scrollbar: {
                    vertical: scrollbarRendering,
                    horizontal: scrollbarRendering,
                    ...options?.scrollbar,
                },
            }}
            value={value}
            {...editorProps}
            onMount={(editor, monaco) => {
                setMonacoAndEditor([monaco, editor])
                initEditor(monaco, editor, editorProps, options ?? {}, monacoDisposables, builtCodeEditorLogic)
                onMount?.(editor, monaco)
            }}
        />
    )
}
