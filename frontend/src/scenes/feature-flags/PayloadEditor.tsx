import { useState } from 'react'
import MonacoEditor from '@monaco-editor/react'
import './PayloadEditor.scss'

interface EditorProps {
    onChange?: (val: string | undefined) => void
}

export function PayloadEditor({ onChange }: EditorProps): JSX.Element {
    const lineHeight = 20
    const defaultLines = 2
    const defaultHeight = lineHeight * defaultLines
    const [height, setHeight] = useState(defaultHeight)

    const updateHeight = (val: string | undefined): void => {
        if (val) {
            const lineCount = val.split(/\r\n|\r|\n/).length
            const newLineCount = Math.max(lineCount + 1, defaultLines)
            setHeight(newLineCount * 20)
        } else {
            setHeight(defaultHeight)
        }
    }

    return (
        <div className="hog-editor">
            <MonacoEditor
                theme="vs-light"
                className="border"
                language={'json'}
                value={''}
                height={height}
                options={{
                    lineHeight: 20,
                    minimap: {
                        enabled: false,
                    },
                    scrollbar: {
                        vertical: 'hidden',
                        horizontal: 'hidden',
                    },
                    padding: {
                        bottom: 0,
                        top: 10,
                    },
                    overviewRulerLanes: 0,
                    hideCursorInOverviewRuler: true,
                    overviewRulerBorder: false,
                    glyphMargin: true,
                    folding: false,
                    lineNumbers: 'off',
                    lineDecorationsWidth: 0,
                    lineNumbersMinChars: 0,
                    renderLineHighlight: 'none',
                    cursorStyle: 'block-outline',
                    scrollBeyondLastLine: false,
                    quickSuggestions: false,
                    contextmenu: false,
                }}
                onChange={(val) => {
                    updateHeight(val)
                    onChange?.(val)
                }}
            />
        </div>
    )
}
