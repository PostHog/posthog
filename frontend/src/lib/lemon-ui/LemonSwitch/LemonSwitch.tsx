import './LemonSwitch.scss'

import clsx from 'clsx'
import { forwardRef, useMemo, useState } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

export interface LemonSwitchProps {
    className?: string
    onChange?: (newChecked: boolean) => void
    checked: boolean
    label?: string | JSX.Element
    labelClassName?: string
    id?: string
    fullWidth?: boolean
    size?: 'xxsmall' | 'xsmall' | 'small' | 'medium'
    bordered?: boolean
    disabled?: boolean
    /** Like plain `disabled`, except we enforce a reason to be shown in the tooltip. */
    disabledReason?: string | null | false
    'data-attr'?: string
    tooltip?: string | JSX.Element | null
    'aria-label'?: string
    sliderColorOverrideChecked?: string
    sliderColorOverrideUnchecked?: string
    loading?: boolean
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
            sliderColorOverrideChecked,
            sliderColorOverrideUnchecked,
            loading = false,
        },
        ref
    ): JSX.Element {
        const id = useMemo(() => rawId || `lemon-switch-${switchCounter++}`, [rawId])
        const [isActive, setIsActive] = useState(false)

        const conditionalProps: { 'aria-label'?: string } = {}
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

        // Disable the switch when loading
        const isDisabled = disabled || loading

        const ButtonHtmlComponent = onChange ? 'button' : 'div'

        let buttonComponent = (
            <ButtonHtmlComponent
                id={id}
                className={`LemonSwitch__button ${
                    sliderColorOverrideChecked || sliderColorOverrideUnchecked
                        ? `bg-${checked ? sliderColorOverrideChecked : sliderColorOverrideUnchecked}`
                        : ''
                }`}
                type="button"
                role="switch"
                onClick={() => {
                    if (onChange && !loading) {
                        onChange(!checked)
                    }
                }}
                onMouseDown={() => !loading && setIsActive(true)}
                onMouseUp={() => setIsActive(false)}
                onMouseOut={() => setIsActive(false)}
                data-attr={dataAttr}
                disabled={isDisabled}
                {...conditionalProps}
            >
                <div className="LemonSwitch__handle">
                    {loading && (
                        <div
                            className={cn(
                                'absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 flex pointer-events-none'
                            )}
                        >
                            <Spinner textColored={true} className="LemonSwitch__spinner-icon" />
                        </div>
                    )}
                </div>
            </ButtonHtmlComponent>
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
                    'LemonSwitch--disabled': isDisabled,
                    'LemonSwitch--full-width': fullWidth,
                    'LemonSwitch--loading': loading,
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
