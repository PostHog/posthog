import './JSONEditorInput.scss'

import { useEffect, useRef, useState } from 'react'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { JsonType } from '~/types'

interface EditorProps {
    onChange?: (val: string | undefined) => void
    value?: JsonType
    readOnly?: boolean
    placeholder?: string
}

// Pretty-print objects and JSON-string values (objects/arrays) with 2-space indentation so payloads
// are readable. Bare strings, numbers, and partial/invalid input are passed through untouched so the
// editor never fights the user mid-typing.
function formatJSON(value: JsonType): string {
    if (typeof value === 'object') {
        // Includes `null` -> 'null', matching the prior rendering for null payloads
        return JSON.stringify(value, null, 2)
    }
    const str = value?.toString() || ''
    try {
        const parsed = JSON.parse(str)
        if (parsed !== null && typeof parsed === 'object') {
            return JSON.stringify(parsed, null, 2)
        }
    } catch {
        // Not valid JSON (e.g. still being typed) — leave it as-is
    }
    return str
}

export function JSONEditorInput({ onChange, placeholder, value = '', readOnly = false }: EditorProps): JSX.Element {
    const [focused, setFocused] = useState(false)

    // The editor is the source of truth for what's displayed. We seed it from `value` (pretty-printed)
    // and only re-sync when `value` changes externally — never on the echo of our own onChange, which
    // would reformat while the user types and jump the cursor.
    const [valString, setValString] = useState<string>(() => formatJSON(value))
    const lastEmitted = useRef<string | undefined>(undefined)

    useEffect(() => {
        // Normalize to a string so the comparison is type-safe even when `value` is an object —
        // `onChange` only ever emits strings, so an object `value` is always an external change.
        const incoming = typeof value === 'object' ? JSON.stringify(value) : (value?.toString() ?? '')
        if (incoming !== lastEmitted.current) {
            setValString(formatJSON(value))
        }
    }, [value])

    const handleChange = (val: string | undefined): void => {
        lastEmitted.current = val
        setValString(val ?? '')
        onChange?.(val)
    }

    const onFocus = (): void => setFocused(true)
    const onBlur = (): void => {
        setFocused(false)
        // Tidy up the user's edits once they leave the field, but only if it actually changes something.
        if (!readOnly) {
            const formatted = formatJSON(valString)
            if (formatted !== valString) {
                handleChange(formatted)
            }
        }
    }

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
                onChange={handleChange}
            />
            {!focused && !valString && placeholder && (
                <div className="placeholder">
                    <div className="placeholderLabelContainer">{placeholder}</div>
                </div>
            )}
        </div>
    )
}
