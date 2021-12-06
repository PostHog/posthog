import clsx from 'clsx'
import React, { useState } from 'react'
import './LemonSwitch.scss'

export interface LemonSwitchProps {
    id?: string
    onChange: (newChecked: boolean) => void
    checked: boolean
    loading?: boolean
    label?: string
    /** Whether the switch should use the alternative primary color. */
    alt?: boolean
    style?: React.CSSProperties
    disabled?: boolean
}

export function LemonSwitch({
    id,
    onChange,
    checked,
    loading,
    label,
    alt,
    style,
    disabled,
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
        >
            <div className="LemonSwitch__slider" />
            <div className="LemonSwitch__handle" />
        </button>
    )

    return label ? (
        <div style={{ display: 'flex', alignItems: 'center', padding: '0 0.25rem' }}>
            <label
                style={{
                    marginRight: '0.375rem',
                }}
                htmlFor={id}
            >
                {label}
            </label>
            {button}
        </div>
    ) : (
        button
    )
}
