import './JSONEditorInput.scss'

import { useMemo, useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { JsonType } from '~/types'

interface EditorProps {
    onChange?: (val: string | undefined) => void
    value?: JsonType
    readOnly?: boolean
    placeholder?: string
}

function looksMultiline(val: string): boolean {
    try {
        const parsed = JSON.parse(val)
        return typeof parsed === 'object' && parsed !== null
    } catch {
        return val.includes('\n')
    }
}

export function JSONEditorInput({ onChange, placeholder, value = '', readOnly = false }: EditorProps): JSX.Element {
    const [focused, setFocused] = useState(false)

    const valString = useMemo(
        () => (typeof value === 'object' ? JSON.stringify(value, null, 2) : value?.toString() || ''),
        [value]
    )

    const [multiline, setMultiline] = useState(() => looksMultiline(valString))

    const onFocus = (): void => setFocused(true)
    const onBlur = (): void => setFocused(false)

    const toggleMultiline = (): void => {
        if (multiline && valString) {
            // Switching to single-line: compact the JSON
            try {
                const parsed = JSON.parse(valString)
                onChange?.(JSON.stringify(parsed))
            } catch {
                // Not valid JSON, just leave as-is
            }
        } else if (!multiline && valString) {
            // Switching to multi-line: pretty-print the JSON
            try {
                const parsed = JSON.parse(valString)
                onChange?.(JSON.stringify(parsed, null, 2))
            } catch {
                // Not valid JSON, just leave as-is
            }
        }
        setMultiline(!multiline)
    }

    return (
        <div className="JsonEditorInput" onFocus={onFocus} onBlur={onBlur}>
            {multiline ? (
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
            ) : (
                <LemonInput
                    className="font-mono text-xs"
                    value={valString}
                    onChange={(val) => onChange?.(val || undefined)}
                    placeholder={placeholder}
                    disabled={readOnly}
                    fullWidth
                />
            )}
            {multiline && !focused && !valString && placeholder && (
                <div className="placeholder">
                    <div className="placeholderLabelContainer">{placeholder}</div>
                </div>
            )}
            {!readOnly && (
                <LemonButton
                    className="JsonEditorInput__toggle"
                    size="xsmall"
                    icon={multiline ? <IconCollapse /> : <IconExpand />}
                    onClick={toggleMultiline}
                    tooltip={multiline ? 'Switch to single-line' : 'Switch to multi-line editor'}
                />
            )}
        </div>
    )
}
