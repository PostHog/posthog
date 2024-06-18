import './CodeEditor.scss'

import MonacoEditor, { type EditorProps, Monaco } from '@monaco-editor/react'
import { useMountedLogic, useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { codeEditorLogic } from 'lib/monaco/codeEditorLogic'
import { hogQLAutocompleteProvider } from 'lib/monaco/hogQLAutocompleteProvider'
import { hogQLMetadataProvider } from 'lib/monaco/hogQLMetadataProvider'
import * as hog from 'lib/monaco/languages/hog'
import * as hogQL from 'lib/monaco/languages/hogql'
import { inStorybookTestRunner } from 'lib/utils'
import type { editor as importedEditor, IDisposable } from 'monaco-editor'
import { useEffect, useRef, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export interface CodeEditorProps extends Omit<EditorProps, 'loading' | 'theme'> {
    queryKey?: string
}
let codeEditorIndex = 0

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
                wordWrap: 'off',
                lineNumbers: 'on',
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
                if (editorProps?.language === 'hog') {
                    if (!monaco.languages.getLanguages().some(({ id }) => id === 'hog')) {
                        monaco.languages.register({ id: 'hog', extensions: ['.hog'], mimetypes: ['application/hog'] })
                        monaco.languages.setLanguageConfiguration('hog', hog.conf)
                        monaco.languages.setMonarchTokensProvider('hog', hog.language)
                    }
                    monacoDisposables.current.push(
                        monaco.languages.registerCodeActionProvider('hog', hogQLMetadataProvider(builtCodeEditorLogic))
                    )
                }
                if (editorProps?.language === 'hogql') {
                    if (!monaco.languages.getLanguages().some(({ id }) => id === 'hogql')) {
                        monaco.languages.register({
                            id: 'hogql',
                            extensions: ['.sql', '.hogql'],
                            mimetypes: ['application/hog+ql'],
                        })
                        monaco.languages.setLanguageConfiguration('hogql', hogQL.conf)
                        monaco.languages.setMonarchTokensProvider('hogql', hogQL.language)
                    }
                    monacoDisposables.current.push(
                        monaco.languages.registerCompletionItemProvider(
                            'hogql',
                            hogQLAutocompleteProvider(builtCodeEditorLogic)
                        )
                    )
                    monacoDisposables.current.push(
                        monaco.languages.registerCodeActionProvider(
                            'hogql',
                            hogQLMetadataProvider(builtCodeEditorLogic)
                        )
                    )
                }
                onMount?.(editor, monaco)
            }}
        />
    )
}
