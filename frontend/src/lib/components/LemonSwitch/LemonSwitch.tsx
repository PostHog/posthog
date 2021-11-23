import clsx from 'clsx'
import React, { useState } from 'react'
import './LemonSwitch.scss'

export interface LemonSwitchProps {
    id?: string
    onChange?: (newChecked: boolean) => void
    onClick?: React.MouseEventHandler<HTMLButtonElement>
    checked?: boolean
    defaultChecked?: boolean
    loading?: boolean
    disabled?: boolean
    /** Whether the switch should use the alternative primary color. */
    alt?: boolean
    style?: React.CSSProperties
}

export function LemonSwitch({ id, onChange, onClick, checked,disabled, defaultChecked = false, loading, alt, style }: LemonSwitchProps): JSX.Element {
    const [internalChecked, setInternalChecked] = useState(defaultChecked)
    const [isActive, setIsActive] = useState(false)

    const realChecked = checked ?? internalChecked

    return (
        <button
            id={id}
            type="button"
            role="switch"
            disabled={disabled}
            className={clsx(
                'LemonSwitch',
                realChecked && 'LemonSwitch--checked',
                isActive && 'LemonSwitch--active',
                loading && 'LemonSwitch--loading',
                alt && 'LemonSwitch--alt'
            )}
            onClick={(e) => {
                if (!loading) {
                    onClick?.(e)
                    setInternalChecked(!realChecked)
                    onChange?.(!realChecked)
                }
            }}
            onMouseDown={() => setIsActive(true)}
            onMouseUp={() => setIsActive(false)}
            onMouseOut={() => setIsActive(false)}
            style={style}
        >
            <div className="LemonSwitch__slider" />
            <div className="LemonSwitch__handle" />
        </button>
    )
}
