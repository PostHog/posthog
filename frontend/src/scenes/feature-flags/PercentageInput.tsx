import { useEffect, useRef, useState } from 'react'

function clampPercentage(value: number): number {
    return Math.round(Math.min(100, Math.max(0, value)) * 100) / 100
}

/** A percentage input (0–100) that allows clearing the field while typing.
 *  Uses a native text input with local string state to avoid React's
 *  controlled <input type="number"> limitation where empty fields snap back. */
export function PercentageInput({
    value,
    onChange,
    className,
    ...rest
}: {
    value: number
    onChange: (value: number) => void
    step?: number
    className?: string
    'data-attr'?: string
}): JSX.Element {
    const [localValue, setLocalValue] = useState(String(value))
    const isFocusedRef = useRef(false)

    // Sync from parent when not focused (e.g. slider changes, distribute evenly)
    useEffect(() => {
        if (!isFocusedRef.current) {
            setLocalValue(String(value))
        }
    }, [value])

    return (
        <span className="LemonInput input-like LemonInput--type-number LemonInput--medium LemonInput--full-width">
            <input
                className={`LemonInput__input ${className ?? ''}`}
                type="text"
                inputMode="decimal"
                value={localValue}
                onChange={(e) => {
                    const raw = e.target.value
                    // Only allow digits, decimal point, and empty
                    if (raw !== '' && !/^\d*\.?\d*$/.test(raw)) {
                        return
                    }
                    const parsed = parseFloat(raw)
                    if (isNaN(parsed)) {
                        // An empty or partial entry keeps the text, but stores 0 straight away,
                        // so validation and save never run on the value the field dropped.
                        setLocalValue(raw)
                        onChange(0)
                        return
                    }
                    const clamped = clampPercentage(parsed)
                    // Show the stored number as soon as clamping or rounding changes it.
                    setLocalValue(clamped === parsed ? raw : String(clamped))
                    onChange(clamped)
                }}
                onFocus={() => {
                    isFocusedRef.current = true
                }}
                onBlur={() => {
                    isFocusedRef.current = false
                    const parsed = parseFloat(localValue)
                    if (isNaN(parsed) || localValue.trim() === '') {
                        onChange(0)
                        setLocalValue('0')
                    } else {
                        const clamped = clampPercentage(parsed)
                        onChange(clamped)
                        setLocalValue(String(clamped))
                    }
                }}
                data-attr={rest['data-attr']}
            />
            <span className="LemonInput__suffix">%</span>
        </span>
    )
}
