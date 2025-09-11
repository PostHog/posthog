import './LemonCheckbox.scss'

import clsx from 'clsx'
import { ChangeEvent, useEffect, useMemo, useState } from 'react'

import { Tooltip } from '../Tooltip'

export interface LemonCheckboxProps {
    checked?: boolean | 'indeterminate'
    defaultChecked?: boolean
    /** @deprecated Checkboxes should never be quietly disabled. Use `disabledReason` to provide an explanation instead. */
    disabled?: boolean
    /** Like plain `disabled`, except we enforce a reason to be shown in the tooltip. */
    disabledReason?: string | null | false
    onChange?: (value: boolean, event: ChangeEvent<HTMLInputElement>) => void
    label?: string | JSX.Element
    id?: string
    className?: string
    labelClassName?: string
    fullWidth?: boolean
    size?: 'xsmall' | 'small' | 'medium'
    bordered?: boolean
    /** @deprecated See https://github.com/PostHog/posthog/pull/9357#pullrequestreview-933783868. */
    color?: string
    'data-attr'?: string
    /** Whether to stop propagation of events from the input */
    stopPropagation?: boolean
}

export interface BoxCSSProperties extends React.CSSProperties {
    '--box-color': string
}

/** Counter used for collision-less automatic checkbox IDs. */
let checkboxCounter = 0

/**
 * As opposed to switches, checkboxes don't always have to result in the change being applied immediately.
 * E.g. the change may only be applied when the user clicks "Save" in a form.
 */
export function LemonCheckbox({
    checked,
    defaultChecked,
    disabled,
    disabledReason,
    onChange,
    label,
    id: rawId,
    className,
    labelClassName,
    fullWidth,
    bordered,
    color,
    size,
    'data-attr': dataAttr,
    stopPropagation,
}: LemonCheckboxProps): JSX.Element {
    const indeterminate = checked === 'indeterminate'
    disabled = disabled || !!disabledReason

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

    // Prevent text selection when clicking on the area between the checkbox and the label
    const stopShiftSelection = (e: React.MouseEvent): void => {
        if (e.shiftKey && e.button === 0) {
            e.preventDefault()
        }
    }

    return (
        <Tooltip title={disabledReason ? <i>{disabledReason}</i> : null} placement="top-start">
            <span
                className={clsx(
                    'LemonCheckbox',
                    localChecked && 'LemonCheckbox--checked',
                    wasIndeterminateLast && 'LemonCheckbox--indeterminate',
                    bordered && 'LemonCheckbox--bordered',
                    disabled && 'LemonCheckbox--disabled',
                    fullWidth && 'LemonCheckbox--full-width',
                    size && `LemonCheckbox--${size}`,
                    className
                )}
                data-attr={dataAttr}
                onMouseDownCapture={stopShiftSelection}
                onClick={(e) => {
                    if (stopPropagation) {
                        e.stopPropagation()
                    }
                }}
            >
                <input
                    className="LemonCheckbox__input"
                    type="checkbox"
                    checked={localChecked}
                    defaultChecked={defaultChecked}
                    onChange={(e) => {
                        // NOTE: We only want to setLocalChecked if the component is not controlled externally
                        checked === undefined && setLocalChecked(e.target.checked)
                        onChange?.(e.target.checked, e)
                    }}
                    id={id}
                    disabled={disabled}
                />
                <label
                    htmlFor={id}
                    /* eslint-disable-next-line react/forbid-dom-props */
                    style={color ? ({ '--box-color': color } as BoxCSSProperties) : {}}
                    className={labelClassName}
                >
                    <svg
                        className="LemonCheckbox__box"
                        fill="none"
                        height="16"
                        viewBox="0 0 16 16"
                        width="16"
                        xmlns="http://www.w3.org/2000/svg"
                    >
                        <path d={!wasIndeterminateLast ? 'm3.5 8 3 3 6-6' : 'm3.5 8h9'} strokeWidth="2" />
                    </svg>
                    {label && <span className="LemonCheckbox__label">{label}</span>}
                </label>
            </span>
        </Tooltip>
    )
}
