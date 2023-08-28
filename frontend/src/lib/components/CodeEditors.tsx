import { Spinner } from 'lib/lemon-ui/Spinner'
import { inStorybookTestRunner } from 'lib/utils'
import MonacoEditor, { type EditorProps } from '@monaco-editor/react'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { useValues } from 'kea'

export type CodeEditorProps = Omit<EditorProps, 'loading' | 'theme'>

export function CodeEditor({ options, ...editorProps }: CodeEditorProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const scrollbarRendering = !inStorybookTestRunner() ? 'auto' : 'hidden'

    return (
        <MonacoEditor // eslint-disable-line react/forbid-elements
            theme={isDarkModeOn ? 'vs-dark' : 'vs-light'}
            loading={<Spinner />}
            options={{
                ...options,
                scrollbar: {
                    vertical: scrollbarRendering,
                    horizontal: scrollbarRendering,
                    ...options?.scrollbar,
                },
            }}
            {...editorProps}
        />
    )
}
