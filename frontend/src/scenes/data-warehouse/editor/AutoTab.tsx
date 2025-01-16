import React, { useEffect, useRef } from 'react'

interface AutoTabProps {
    value: string
    onChange: React.ChangeEventHandler<HTMLInputElement>
    onKeyDown?: React.KeyboardEventHandler<HTMLInputElement>
    onBlur: React.FocusEventHandler<HTMLInputElement>
    handleRename: () => void
    autoFocus?: boolean
}

const AutoTab = ({ value, onChange, onKeyDown, onBlur, autoFocus, handleRename }: AutoTabProps): JSX.Element => {
    const inputRef = useRef<HTMLInputElement>(null)
    const mirrorRef = useRef<HTMLSpanElement>(null)

    useEffect(() => {
        if (!inputRef.current || !mirrorRef.current) {
            return
        }
        const newWidth = mirrorRef.current.offsetWidth
        inputRef.current.style.width = newWidth + 'px'
    }, [value])

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
        if (e.target.value.length > 0) {
            onChange(e)
            handleRename()
        }
    }

    return (
        <div className="relative inline-block">
            <span ref={mirrorRef} className="pointer-events-none absolute invisible whitespace-pre" aria-hidden="true">
                {value}
            </span>
            <input
                ref={inputRef}
                className="bg-transparent border-none focus:outline-none p-0"
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
