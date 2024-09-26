import './LemonSwitch.scss'

import clsx from 'clsx'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { forwardRef, useMemo, useState } from 'react'

export interface LemonSwitchProps {
    className?: string
    onChange?: (newChecked: boolean) => void
    checked: boolean
    label?: string | JSX.Element
    labelClassName?: string
    id?: string
    fullWidth?: boolean
    size?: 'small' | 'medium'
    bordered?: boolean
    disabled?: boolean
    /** Like plain `disabled`, except we enforce a reason to be shown in the tooltip. */
    disabledReason?: string | null | false
    'data-attr'?: string
    tooltip?: string | JSX.Element | null
    handleContent?: React.ReactElement | null
    'aria-label'?: string
    sliderColorOverrideChecked?: string
    sliderColorOverrideUnchecked?: string
}

/** Counter used for collision-less automatic switch IDs. */
let switchCounter = 0

export const LemonSwitch: React.FunctionComponent<LemonSwitchProps & React.RefAttributes<HTMLDivElement>> = forwardRef(
    function LemonSwitch(
        {
            className,
            id: rawId,
            onChange,
            checked,
            fullWidth,
            bordered,
            size = 'medium',
            disabled,
            disabledReason,
            label,
            labelClassName,
            tooltip,
            'data-attr': dataAttr,
            'aria-label': ariaLabel,
            handleContent,
            sliderColorOverrideChecked,
            sliderColorOverrideUnchecked,
        },
        ref
    ): JSX.Element {
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
        } else if (tooltip) {
            tooltipContent = <span>{tooltip}</span>
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
                <div
                    className={`LemonSwitch__slider ${
                        sliderColorOverrideChecked || sliderColorOverrideUnchecked
                            ? `bg-${checked ? sliderColorOverrideChecked : sliderColorOverrideUnchecked}`
                            : ''
                    }`}
                />
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
                ref={ref}
                className={clsx('LemonSwitch', className, `LemonSwitch--${size}`, {
                    'LemonSwitch--checked': checked,
                    'LemonSwitch--active': isActive,
                    'LemonSwitch--bordered': bordered,
                    'LemonSwitch--disabled': disabled,
                    'LemonSwitch--full-width': fullWidth,
                })}
            >
                {label && (
                    <label htmlFor={id} className={labelClassName}>
                        {label}
                    </label>
                )}
                {buttonComponent}
            </div>
        )
    }
)
