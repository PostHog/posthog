import clsx from 'clsx'
import React, { useState } from 'react'
import './LemonSwitch.scss'

export interface LemonSwitchProps {
    id?: string
    onChange: (newChecked: boolean) => void
    checked: boolean
    loading?: boolean
    label?: string | JSX.Element
    /** Whether the switch should use the alternative primary color. */
    alt?: boolean
    /** Whether the switch should be wrapped in an outlined block for visual distinction */
    block?: boolean
    style?: React.CSSProperties
    wrapperStyle?: React.CSSProperties
    disabled?: boolean
    'data-attr'?: string
}

export function LemonSwitch({
    id,
    onChange,
    checked,
    loading,
    label,
    alt,
    block,
    style,
    wrapperStyle,
    disabled,
    'data-attr': dataAttr,
}: LemonSwitchProps): JSX.Element {
    const [isActive, setIsActive] = useState(false)

    const button = (
        <button
            id={id}
            type="button"
            role="switch"
            className={clsx(
                'LemonSwitch',
                checked && 'LemonSwitch--checked',
                isActive && 'LemonSwitch--active',
                loading && 'LemonSwitch--loading',
                alt && 'LemonSwitch--alt',
                disabled && 'LemonSwitch--disabled'
            )}
            onClick={() => onChange(!checked)}
            onMouseDown={() => setIsActive(true)}
            onMouseUp={() => setIsActive(false)}
            onMouseOut={() => setIsActive(false)}
            style={style}
            disabled={disabled}
            data-attr={dataAttr}
        >
            <div className="LemonSwitch__slider" />
            <div className="LemonSwitch__handle" />
        </button>
    )

    return label ? (
        <div className={clsx('LemonSwitch__wrapper', block && 'LemonSwitch__wrapper--block')} style={wrapperStyle}>
            <label className="LemonSwitch__label" htmlFor={id}>
                {label}
            </label>
            {button}
        </div>
    ) : (
        button
    )
}
