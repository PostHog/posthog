import { useEffect, useRef, useState } from 'react'

import { LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { isObject } from 'lib/utils/guards'
import { objectsEqual } from 'lib/utils/objects'

import { FeatureFlagRulesV2ReturnType, JsonType } from '~/types'

import { JSONEditorInput } from './JSONEditorInput'

const BOOLEAN_OPTIONS = [
    { value: 'true', label: 'true' },
    { value: 'false', label: 'false' },
]

function objectInputText(value: JsonType | null): string {
    if (value === null) {
        return ''
    }
    return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

/** The object the text holds, or the text itself while it holds none, so the draft's validation flags it. */
function objectInputValue(text: string, nullable: boolean): JsonType | null {
    if (nullable && text.trim() === '') {
        return null
    }
    try {
        const parsed: unknown = JSON.parse(text)
        if (isObject(parsed)) {
            return parsed as JsonType
        }
    } catch {
        // Not JSON yet.
    }
    return text
}

function RulesV2ObjectInput({
    value,
    onChange,
    nullable,
    id,
    className,
    ariaLabel,
    dataAttr,
}: {
    value: JsonType | null
    onChange: (value: JsonType | null) => void
    nullable: boolean
    id?: string
    className?: string
    ariaLabel?: string
    dataAttr?: string
}): JSX.Element {
    // The text keeps the user's formatting; only a value set from outside, such as a discard, replaces it.
    const [text, setText] = useState(() => objectInputText(value))
    const emitted = useRef(value)
    useEffect(() => {
        if (!objectsEqual(value, emitted.current)) {
            emitted.current = value
            setText(objectInputText(value))
        }
    }, [value])

    return (
        <div role="group" id={id} aria-label={ariaLabel} data-attr={dataAttr} className={`min-w-0 ${className ?? ''}`}>
            <JSONEditorInput
                value={text}
                placeholder={nullable ? 'No value' : 'A JSON object'}
                onChange={(next = '') => {
                    const parsed = objectInputValue(next, nullable)
                    emitted.current = parsed
                    setText(next)
                    onChange(parsed)
                }}
            />
        </div>
    )
}

/**
 * A value of the flag's return type. A boolean is always true or false. A nullable string, number or object value is
 * null while its input is empty. An
 * object input holds its text until it parses to an object, so the draft shows the error rather than dropping the edit.
 */
export function RulesV2ValueInput({
    returnType,
    value,
    onChange,
    nullable = false,
    id,
    className,
    'aria-label': ariaLabel,
    'data-attr': dataAttr,
}: {
    returnType: FeatureFlagRulesV2ReturnType
    value: JsonType | null
    onChange: (value: JsonType | null) => void
    nullable?: boolean
    id?: string
    className?: string
    'aria-label'?: string
    'data-attr'?: string
}): JSX.Element {
    if (returnType === 'object') {
        return (
            <RulesV2ObjectInput
                value={value}
                onChange={onChange}
                nullable={nullable}
                id={id}
                className={className}
                ariaLabel={ariaLabel}
                dataAttr={dataAttr}
            />
        )
    }
    if (returnType === 'number') {
        return (
            <LemonInput
                type="number"
                id={id}
                aria-label={ariaLabel}
                // NaN shows an empty field and, unlike undefined, keeps the input controlled.
                value={typeof value === 'number' ? value : NaN}
                // An empty or half-typed number reads as NaN.
                onChange={(number) => onChange(number === undefined || Number.isNaN(number) ? null : number)}
                placeholder={nullable ? 'No value' : 'Value to serve'}
                step="any"
                className={`ph-ignore-input font-mono ${className ?? ''}`}
                size="small"
                data-attr={dataAttr}
            />
        )
    }
    if (returnType === 'string') {
        return (
            <LemonInput
                id={id}
                aria-label={ariaLabel}
                value={typeof value === 'string' ? value : ''}
                onChange={(text) => onChange(nullable && text === '' ? null : text)}
                placeholder={nullable ? 'No value' : 'Value to serve'}
                className={`ph-ignore-input font-mono ${className ?? ''}`}
                size="small"
                autoComplete="off"
                spellCheck={false}
                data-attr={dataAttr}
            />
        )
    }
    // LemonSegmentedButton drops these props, so a labelled group carries them.
    return (
        <div role="group" id={id} aria-label={ariaLabel} data-attr={dataAttr} className={className}>
            <LemonSegmentedButton
                size="small"
                value={String(value)}
                onChange={(option) => onChange(option === 'true')}
                options={BOOLEAN_OPTIONS}
            />
        </div>
    )
}
