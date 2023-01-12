import { useState } from 'react'
import MonacoEditor from '@monaco-editor/react'
import './JSONEditorInput.scss'
import { JsonType } from '~/types'

interface EditorProps {
    onChange?: (val: string | undefined) => void
    lineHeight?: number
    defaultNumberOfLines?: number
    value?: JsonType
    readOnly?: boolean
}

export function JSONEditorInput({
    onChange,
    lineHeight = 20,
    defaultNumberOfLines = 1,
    value = '',
    readOnly = false,
}: EditorProps): JSX.Element {
    const valString = value?.toString() || ''
    const _lineHeight = lineHeight
    const defaultLines = Math.max(defaultNumberOfLines, valString.split(/\r\n|\r|\n/).length) + 1
    const defaultHeight = _lineHeight * defaultLines
    const [height, setHeight] = useState(defaultHeight)

    const updateHeight = (val: string | undefined): void => {
        if (val) {
            const lineCount = val.split(/\r\n|\r|\n/).length
            const newLineCount = Math.max(lineCount, defaultNumberOfLines) + 1
            setHeight(_lineHeight * newLineCount)
        } else {
            setHeight(_lineHeight * (defaultNumberOfLines + 1))
        }
    }

    return (
        <div className="hog-editor">
            <MonacoEditor
                theme="vs-light"
                className="border"
                language={'json'}
                height={height}
                value={value?.toString()}
                options={{
                    readOnly: readOnly,
                    lineHeight: _lineHeight,
                    minimap: {
                        enabled: false,
                    },
                    scrollbar: {
                        vertical: 'hidden',
                        horizontal: 'hidden',
                        alwaysConsumeMouseWheel: false,
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
