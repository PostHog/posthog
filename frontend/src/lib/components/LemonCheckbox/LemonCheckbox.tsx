import clsx from 'clsx'
import React, { useEffect, useMemo, useState } from 'react'
import './LemonCheckbox.scss'

export interface LemonCheckboxProps {
    checked?: boolean
    defaultChecked?: boolean
    indeterminate?: boolean
    disabled?: boolean
    onChange?: (event: React.ChangeEvent<HTMLInputElement>) => void
    label?: string | JSX.Element
    id?: string
    className?: string
    style?: React.CSSProperties
    color?: string
}

export function LemonCheckbox({
    checked,
    defaultChecked,
    indeterminate,
    disabled,
    onChange,
    label,
    id,
    className,
    style,
    color,
}: LemonCheckboxProps): JSX.Element {
    const [localChecked, setLocalChecked] = useState(checked ?? defaultChecked)

    useEffect(() => {
        setLocalChecked(checked)
    }, [checked])

    id = useMemo(() => id || `lemon-checkbox-${Math.floor(Math.random() * 1000000)}`, [id])

    return (
        <div
            className={clsx(
                'LemonCheckbox',
                (localChecked || indeterminate) && 'LemonCheckbox--checked',
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
                        d={!indeterminate ? 'm4.04083 7.75543 2.65208 2.65207 5.50709-5.50711' : 'm12.5 8h-9'}
                        strokeWidth="2"
                    />
                </svg>
                <span className="LemonCheckbox__text">{label}</span>
            </label>
        </div>
    )
}
