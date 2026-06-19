import React, { useCallback, useLayoutEffect, useMemo, useState } from 'react'

import { CodeEditor, CodeEditorProps } from 'lib/monaco/CodeEditor'

import { coerceJsonToObject } from '../datasets/utils'

export interface JSONEditorProps {
    onChange?: (val: string | undefined) => void
    lineHeight?: number
    defaultNumberOfLines?: number
    value?: string
    readOnly?: boolean
    maxNumberOfLines?: number
    autoFocus?: boolean
}

export const JSONEditor = React.memo(
    ({
        onChange,
        lineHeight = 20,
        defaultNumberOfLines = 3,
        maxNumberOfLines = 24,
        value = '',
        readOnly = false,
        autoFocus = false,
    }: JSONEditorProps): JSX.Element => {
        const valString = value?.toString() || ''
        const defaultLines = Math.max(defaultNumberOfLines, valString.split(/\r\n|\r|\n/).length) + 1
        const defaultHeight = lineHeight * defaultLines
        const [height, setHeight] = useState(defaultHeight)

        const updateHeight = useCallback(
            (val: string | undefined) => {
                if (val) {
                    const lineCount = val.split(/\r\n|\r|\n/).length
                    const newLineCount = Math.min(Math.max(lineCount, defaultNumberOfLines), maxNumberOfLines) + 1
                    setHeight(lineHeight * newLineCount)
                } else {
                    setHeight(lineHeight * (defaultNumberOfLines + 1))
                }
            },
            [defaultNumberOfLines, lineHeight, maxNumberOfLines]
        )

        // Reset height if the value was reset.
        useLayoutEffect(() => {
            const obj = coerceJsonToObject(value)
            if (!obj && height !== defaultHeight) {
                updateHeight(value)
            }
        }, [value, height, defaultHeight, updateHeight])

        const onTextChange = useCallback(
            (val: string | undefined): void => {
                updateHeight(val)

                if (onChange) {
                    onChange(val)
                }
            },
            [onChange, defaultNumberOfLines, lineHeight, maxNumberOfLines, updateHeight]
        )

        const options = useMemo((): CodeEditorProps['options'] => {
            return {
                readOnly: readOnly,
                lineHeight: lineHeight,
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
            }
        }, [lineHeight, readOnly])

        return (
            <CodeEditor
                className="rounded [&_.monaco-editor]:rounded [&_.monaco-diff-editor]:rounded [&_.overflow-guard]:rounded"
                language="json"
                height={height}
                value={value}
                options={options}
                onChange={onTextChange}
                autoFocus={autoFocus}
            />
        )
    }
)
JSONEditor.displayName = 'JSONEditor'
