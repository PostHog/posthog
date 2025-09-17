import './JSONEditorInput.scss'

import { useState } from 'react'

import { CodeEditor } from 'lib/monaco/CodeEditor'

import { JsonType } from '~/types'

interface EditorProps {
    onChange?: (val: string | undefined) => void
    lineHeight?: number
    defaultNumberOfLines?: number
    value?: JsonType
    readOnly?: boolean
    placeholder?: string
}

export function JSONEditorInput({
    onChange,
    placeholder,
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
    const [focused, setFocused] = useState(false)

    const updateHeight = (val: string | undefined): void => {
        if (val) {
            const lineCount = val.split(/\r\n|\r|\n/).length
            const newLineCount = Math.max(lineCount, defaultNumberOfLines) + 1
            setHeight(_lineHeight * newLineCount)
        } else {
            setHeight(_lineHeight * (defaultNumberOfLines + 1))
        }
    }

    const onFocus = (): void => setFocused(true)
    const onBlur = (): void => setFocused(false)

    return (
        <div className="JsonEditorInput" onFocus={onFocus} onBlur={onBlur}>
            <CodeEditor
                className="border"
                language="json"
                height={height}
                value={value?.toString()}
                options={{
                    readOnly: readOnly,
                    lineHeight: _lineHeight,
                    minimap: {
                        enabled: false,
                    },
                    scrollbar: {
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
                    cursorStyle: 'line',
                    scrollBeyondLastLine: false,
                    quickSuggestions: false,
                    contextmenu: false,
                }}
                onChange={(val) => {
                    updateHeight(val)
                    onChange?.(val)
                }}
            />
            {!focused && !value?.toString() && placeholder && (
                <div className="placeholder">
                    <div className="placeholderLabelContainer">{placeholder}</div>
                </div>
            )}
        </div>
    )
}
