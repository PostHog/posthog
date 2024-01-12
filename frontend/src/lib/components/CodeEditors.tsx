import MonacoEditor, { type EditorProps } from '@monaco-editor/react'
import { useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { inStorybookTestRunner } from 'lib/utils'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

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
                padding: { bottom: 8, top: 8 },
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
