import clsx from 'clsx'
import React, { useMemo, useState } from 'react'
import { Spinner } from '../Spinner/Spinner'
import './LemonSwitch.scss'

export interface LemonSwitchProps {
    onChange?: (newChecked: boolean) => void
    checked: boolean
    label?: string | JSX.Element
    id?: string
    fullWidth?: boolean
    loading?: boolean
    bordered?: boolean
    disabled?: boolean
    'data-attr'?: string
    size?: 'small' | 'medium'
    icon?: React.ReactElement | null
}

/** Counter used for collision-less automatic switch IDs. */
let switchCounter = 0

export function LemonSwitch({
    id: rawId,
    onChange,
    checked,
    loading,
    fullWidth,
    bordered,
    disabled,
    label,
    icon,
    size,
    'data-attr': dataAttr,
}: LemonSwitchProps): JSX.Element {
    const id = useMemo(() => rawId || `lemon-checkbox-${switchCounter++}`, [rawId])
    const [isActive, setIsActive] = useState(false)

    return (
        <div
            className={clsx('LemonSwitch', {
                'LemonSwitch--checked': checked,
                'LemonSwitch--active': isActive,
                'LemonSwitch--bordered': bordered,
                'LemonSwitch--disabled': disabled,
                'LemonSwitch--full-width': fullWidth,
                [`LemonSwitch--${size}`]: size,
            })}
        >
            {icon}
            {label && <label htmlFor={id}>{label}</label>}
            <button
                id={id}
                className="LemonSwitch__button"
                role="switch"
                onClick={() => {
                    if (onChange) {
                        onChange(!checked)
                    }
                }}
                onMouseDown={() => setIsActive(true)}
                onMouseUp={() => setIsActive(false)}
                onMouseOut={() => setIsActive(false)}
                data-attr={dataAttr}
                disabled={disabled}
            >
                <div className="LemonSwitch__slider" />
                <div className="LemonSwitch__handle">
                    {loading && <Spinner size="sm" type={checked ? 'inverse' : 'primary'} traceless />}
                </div>
            </button>
        </div>
    )
}
