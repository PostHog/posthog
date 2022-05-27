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
    /** @deprecated See https://github.com/PostHog/posthog/pull/9357#pullrequestreview-933783868. */
    color?: string
    rowProps?: LemonRowProps<'div'>
}

export interface BoxCSSProperties extends React.CSSProperties {
    '--box-color': string
}

/** Counter used for collision-less automatic checkbox IDs. */
let checkboxCounter = 0

/** `LemonRow`-based checkbox component for use in lists or forms.
 *
 * As opposed to switches, checkboxes don't always have to result in the change being applied immediately.
 * E.g. the change may only be applied when the user clicks "Save" in a form.
 */
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
    style,
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
                className
            )}
            disabled={disabled}
            style={style}
            icon={
                <>
                    <input
                        className="LemonCheckbox__input"
                        type="checkbox"
                        checked={localChecked}
                        defaultChecked={defaultChecked}
                        onChange={(e) => {
                            // NOTE: We only want to setLocalChecked if the component is not controlled externally
                            checked === undefined && setLocalChecked(e.target.checked)
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
                <label className="LemonCheckbox__label" htmlFor={id}>
                    {label}
                </label>
            )}
        </LemonRow>
    )
}
