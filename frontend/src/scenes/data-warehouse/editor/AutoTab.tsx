import React, { useEffect, useRef } from 'react'

interface AutoTabProps {
    value: string
    onChange: React.ChangeEventHandler<HTMLInputElement>
    onKeyDown?: React.KeyboardEventHandler<HTMLInputElement>
    onBlur: React.FocusEventHandler<HTMLInputElement>
    autoFocus?: boolean
}

/**
 * Tab component that automatically resizes an input field to match the width of its content based upon
 * the width of a hidden span element.
 */
const AutoTab = ({ value, onChange, onKeyDown, onBlur, autoFocus }: AutoTabProps): JSX.Element => {
    const inputRef = useRef<HTMLInputElement>(null)
    const spanRef = useRef<HTMLSpanElement>(null)

    useEffect(() => {
        if (!inputRef.current || !spanRef.current) {
            return
        }
        const newWidth = spanRef.current.offsetWidth
        inputRef.current.style.width = newWidth + 'px'
    }, [value])

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
        onChange(e)
    }

    return (
        <div className="relative inline-block">
            <span ref={spanRef} className="pointer-events-none absolute invisible whitespace-pre" aria-hidden="true">
                {value}
            </span>
            <input
                ref={inputRef}
                className="bg-transparent border-none focus:outline-hidden p-0"
                value={value}
                onChange={handleChange}
                onKeyDown={onKeyDown}
                onBlur={onBlur}
                autoFocus={autoFocus}
            />
        </div>
    )
}

export default AutoTab
