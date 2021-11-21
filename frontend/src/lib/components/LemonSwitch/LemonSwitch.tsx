import clsx from 'clsx'
import React, { useState } from 'react'
import './LemonSwitch.scss'

export interface LemonSwitchProps {
    id?: string
    onChange: (newChecked: boolean) => void
    checked: boolean
    loading?: boolean
    /** Whether the switch should use the alternative primary color. */
    alt?: boolean
    style?: React.CSSProperties
    disabled?: boolean
}

export function LemonSwitch({ id, onChange, checked, loading, alt, style }: LemonSwitchProps): JSX.Element {
    const [isActive, setIsActive] = useState(false)

    return (
        <button
            id={id}
            type="button"
            role="switch"
            className={clsx(
                'LemonSwitch',
                checked && 'LemonSwitch--checked',
                isActive && 'LemonSwitch--active',
                loading && 'LemonSwitch--loading',
                alt && 'LemonSwitch--alt'
            )}
            onClick={() => onChange(!checked)}
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
