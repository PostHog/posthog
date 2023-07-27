import clsx from 'clsx'
import { useMemo, useState } from 'react'
import './LemonSwitch.scss'

export interface LemonSwitchProps {
    className?: string
    onChange?: (newChecked: boolean) => void
    checked: boolean
    label?: string | JSX.Element
    labelClassName?: string
    id?: string
    fullWidth?: boolean
    bordered?: boolean
    disabled?: boolean
    'data-attr'?: string
    icon?: React.ReactElement | null
    handleContent?: React.ReactElement | null
    'aria-label'?: string
}

/** Counter used for collision-less automatic switch IDs. */
let switchCounter = 0

export function LemonSwitch({
    className,
    id: rawId,
    onChange,
    checked,
    fullWidth,
    bordered,
    disabled,
    label,
    labelClassName,
    icon,
    'data-attr': dataAttr,
    'aria-label': ariaLabel,
    handleContent,
}: LemonSwitchProps): JSX.Element {
    const id = useMemo(() => rawId || `lemon-switch-${switchCounter++}`, [rawId])
    const [isActive, setIsActive] = useState(false)

    const conditionalProps = {}
    if (ariaLabel) {
        conditionalProps['aria-label'] = ariaLabel
    }

    return (
        <div
            className={clsx('LemonSwitch', className, {
                'LemonSwitch--checked': checked,
                'LemonSwitch--active': isActive,
                'LemonSwitch--bordered': bordered,
                'LemonSwitch--disabled': disabled,
                'LemonSwitch--full-width': fullWidth,
            })}
        >
            {icon}
            {label && (
                <label htmlFor={id} className={labelClassName}>
                    {label}
                </label>
            )}
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
                {...conditionalProps}
            >
                <div className="LemonSwitch__slider" />
                <div className="LemonSwitch__handle">{handleContent}</div>
            </button>
        </div>
    )
}
