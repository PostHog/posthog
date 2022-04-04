import clsx from 'clsx'
import React, { useEffect, useMemo, useState } from 'react'
import './LemonCheckbox.scss'

export interface LemonCheckboxProps {
    checked?: boolean | 'indeterminate'
    defaultChecked?: boolean
    disabled?: boolean
    onChange?: (event: React.ChangeEvent<HTMLInputElement>) => void
    label?: string | JSX.Element
    id?: string
    className?: string
    style?: React.CSSProperties
    color?: string
}

/** Counter used for collision-less automatic checkbox IDs. */
let checkboxCounter = 0

export function LemonCheckbox({
    checked,
    defaultChecked,
    disabled,
    onChange,
    label,
    id: rawId,
    className,
    style,
    color,
}: LemonCheckboxProps): JSX.Element {
    const indeterminate = checked === 'indeterminate'

    const id = useMemo(() => rawId || `lemon-checkbox-${checkboxCounter++}`, [rawId])
    const [localChecked, setLocalChecked] = useState(indeterminate || (checked ?? defaultChecked ?? false))
    const [wasIndeterminateLast, setWasIndeterminateLast] = useState(false)

    useEffect(() => {
        if (checked !== undefined) {
            setLocalChecked(!!checked)
        }
    }, [checked])

    useEffect(() => {
        if (checked) {
            setWasIndeterminateLast(indeterminate)
        }
    }, [checked, indeterminate])

    return (
        <div
            className={clsx(
                'LemonCheckbox',
                localChecked && 'LemonCheckbox--checked',
                disabled && 'LemonCheckbox--disabled',
                className
            )}
            style={style}
        >
            <input
                type="checkbox"
                checked={localChecked}
                defaultChecked={defaultChecked}
                onChange={(e) => {
                    setLocalChecked(e.target.checked)
                    onChange?.(e)
                }}
                id={id}
                disabled={disabled}
            />
            <label htmlFor={id}>
                <svg
                    fill="none"
                    height="16"
                    viewBox="0 0 16 16"
                    width="16"
                    xmlns="http://www.w3.org/2000/svg"
                    className="LemonCheckbox__box"
                    style={checked && color ? { background: color } : {}}
                >
                    <path
                        d={!wasIndeterminateLast ? 'm4.04083 7.75543 2.65208 2.65207 5.50709-5.50711' : 'm3.5 8h9'}
                        strokeWidth="2"
                    />
                </svg>
                <span className="LemonCheckbox__text">{label}</span>
            </label>
        </div>
    )
}
