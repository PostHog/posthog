import './LemonSwitch.scss'

import clsx from 'clsx'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useMemo, useState } from 'react'

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
    /** Like plain `disabled`, except we enforce a reason to be shown in the tooltip. */
    disabledReason?: string | null | false
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
    disabledReason,
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

    let tooltipContent: JSX.Element | null = null
    if (disabledReason) {
        disabled = true // Support `disabledReason` while maintaining compatibility with `disabled`
        tooltipContent = <span className="italic">{disabledReason}</span>
    }
    let buttonComponent = (
        <button
            id={id}
            className="LemonSwitch__button"
            type="button"
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
    )
    if (tooltipContent) {
        buttonComponent = (
            <Tooltip title={tooltipContent}>
                {/* wrap it in a div so that the tooltip works even when disabled */}
                <div className="flex items-center">{buttonComponent}</div>
            </Tooltip>
        )
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
            {buttonComponent}
        </div>
    )
}
