import clsx from 'clsx'
import React, { useEffect, useMemo, useState } from 'react'
import { LemonRow, LemonRowProps } from '../LemonRow'
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
    rowProps?: LemonRowProps<'div'>
}

export interface BoxCSSProperties extends React.CSSProperties {
    '--box-color': string
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
    color,
    rowProps,
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
        <LemonRow
            className={clsx(
                'LemonCheckbox',
                localChecked && 'LemonCheckbox--checked',
                wasIndeterminateLast && 'LemonCheckbox--indeterminate',
                disabled && 'LemonCheckbox--disabled',
                className
            )}
            icon={
                <>
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

                    <label
                        htmlFor={id}
                        className="LemonCheckbox__box"
                        style={color ? ({ '--box-color': color } as BoxCSSProperties) : {}}
                    >
                        <svg fill="none" height="16" viewBox="0 0 16 16" width="16" xmlns="http://www.w3.org/2000/svg">
                            <path d={!wasIndeterminateLast ? 'm3.5 8 3 3 6-6' : 'm3.5 8h9'} strokeWidth="2" />
                        </svg>
                    </label>
                </>
            }
            {...rowProps}
        >
            {label && (
                <label htmlFor={id} className="LemonCheckbox__text">
                    {label}
                </label>
            )}
        </LemonRow>
    )
}
