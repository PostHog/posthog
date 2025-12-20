import './JSONEditorInput.scss'

import { useMemo, useState } from 'react'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { JsonType } from '~/types'

interface EditorProps {
    onChange?: (val: string | undefined) => void
    value?: JsonType
    readOnly?: boolean
    placeholder?: string
}

export function JSONEditorInput({ onChange, placeholder, value = '', readOnly = false }: EditorProps): JSX.Element {
    const [focused, setFocused] = useState(false)

    // Memoize the string conversion to avoid recalculating on every render
    // In practice, `value` is always a string, but the type allows for object too
    const valString = useMemo(
        () => (typeof value === 'object' ? JSON.stringify(value, null, 2) : value?.toString() || ''),
        [value]
    )

    const onFocus = (): void => setFocused(true)
    const onBlur = (): void => setFocused(false)

    return (
        <div className="JsonEditorInput" onFocus={onFocus} onBlur={onBlur}>
            <CodeEditorResizeable
                className="border input-like"
                language="json"
                value={valString}
                minHeight={37}
                maxHeight="24em"
                embedded
                allowManualResize={!readOnly}
                options={{
                    readOnly: readOnly,
                    minimap: {
                        enabled: false,
                    },
                    scrollbar: {
                        alwaysConsumeMouseWheel: false,
                    },
                    overviewRulerLanes: 0,
                    hideCursorInOverviewRuler: true,
                    overviewRulerBorder: false,
                    glyphMargin: false,
                    folding: false,
                    lineNumbers: 'off',
                    lineDecorationsWidth: 7,
                    renderWhitespace: 'trailing',
                    lineNumbersMinChars: 0,
                    renderLineHighlight: 'none',
                    cursorStyle: 'line',
                    scrollBeyondLastLine: false,
                    quickSuggestions: false,
                    contextmenu: false,
                }}
                onChange={onChange}
            />
            {!focused && !valString && placeholder && (
                <div className="placeholder">
                    <div className="placeholderLabelContainer">{placeholder}</div>
                </div>
            )}
        </div>
    )
}
