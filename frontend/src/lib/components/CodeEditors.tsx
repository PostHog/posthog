import './CodeEditor.scss'

import MonacoEditor, { type EditorProps } from '@monaco-editor/react'
import { useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { inStorybookTestRunner } from 'lib/utils'
import { useEffect, useState } from 'react'
import AutoSizer from 'react-virtualized/dist/es/AutoSizer'

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
                // :TRICKY: We need to declare all options here, as omitting something will carry its value from one <CodeEditor> to another.
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
            {...editorProps}
        />
    )
}

export function CodeEditorResizeable({
    height: defaultHeight = 200,
    minHeight = '5rem',
    maxHeight = '90vh',
    ...props
}: Omit<CodeEditorProps, 'height'> & {
    height?: number
    minHeight?: string | number
    maxHeight?: string | number
}): JSX.Element {
    const [height, setHeight] = useState(defaultHeight ?? 200)
    const [manualHeight, setManualHeight] = useState<number>()

    useEffect(() => {
        const value = typeof props.value !== 'string' ? JSON.stringify(props.value, null, 2) : props.value
        const lineCount = (value?.split('\n').length ?? 1) + 1
        const lineHeight = 18
        setHeight(lineHeight * lineCount)
    }, [props.value])

    return (
        <div
            className="CodeEditorResizeable relative border rounded"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                minHeight,
                maxHeight,
                height: manualHeight ?? height,
            }}
        >
            <AutoSizer disableWidth>
                {({ height }) => (
                    <CodeEditor
                        {...props}
                        height={height - 2} // Account for border
                    />
                )}
            </AutoSizer>

            {/* Using a standard resize css means we need overflow-hidden which hides parts of the editor unnecessarily */}
            <div
                className="absolute bottom-0 right-0 z-10 resize-y h-5 w-5 cursor-s-resize overflow-hidden"
                onMouseDown={(e) => {
                    const startY = e.clientY
                    const startHeight = height
                    const onMouseMove = (event: MouseEvent): void => {
                        setManualHeight(startHeight + event.clientY - startY)
                    }
                    const onMouseUp = (): void => {
                        window.removeEventListener('mousemove', onMouseMove)
                        window.removeEventListener('mouseup', onMouseUp)
                    }
                    window.addEventListener('mousemove', onMouseMove)
                    window.addEventListener('mouseup', onMouseUp)
                }}
            />
        </div>
    )
}
