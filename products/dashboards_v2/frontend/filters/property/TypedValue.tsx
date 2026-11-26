import { useState } from 'react'

import { Input } from '@posthog/quill'

import type { OperatorOption, PropertyCondition } from './propertyOperators'

export function TypedValue({
    option,
    value,
    onChange,
}: {
    option: OperatorOption
    value: PropertyCondition['value']
    onChange: (value: string | number | undefined) => void
}): JSX.Element {
    const [text, setText] = useState(Array.isArray(value) || value === undefined ? '' : String(value))
    const commit = (): void => {
        const trimmed = text.trim()
        if (!trimmed) {
            onChange(undefined)
            return
        }
        onChange(option.input === 'number' ? Number(trimmed) : trimmed)
    }
    return (
        <Input
            autoFocus
            type={option.input === 'number' ? 'number' : 'text'}
            placeholder={option.input === 'number' ? 'Type a number' : 'Type a value'}
            value={text}
            onChange={(event) => setText(event.currentTarget.value)}
            onBlur={commit}
            onKeyDown={(event) => event.key === 'Enter' && commit()}
        />
    )
}
