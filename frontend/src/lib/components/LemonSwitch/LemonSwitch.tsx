import clsx from 'clsx'
import React, { useState } from 'react'
import './LemonSwitch.scss'

export interface LemonSwitchProps {
    id?: string
    onChange: (newChecked: boolean) => void
    checked: boolean
    loading?: boolean
}

export function LemonSwitch({ id, onChange, checked, loading }: LemonSwitchProps): JSX.Element {
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
                loading && 'LemonSwitch--loading'
            )}
            onClick={() => onChange(!checked)}
            onMouseDown={() => setIsActive(true)}
            onMouseUp={() => setIsActive(false)}
            onMouseOut={() => setIsActive(false)}
        >
            <div className="LemonSwitch__slider" />
            <div className="LemonSwitch__handle" />
        </button>
    )
}
