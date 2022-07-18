import clsx from 'clsx'
import React, { useMemo, useState } from 'react'
import { LemonRow, LemonRowProps } from '../LemonRow'
import { Spinner } from '../Spinner/Spinner'
import './LemonSwitch.scss'

export interface LemonSwitchProps extends Omit<LemonRowProps<'div'>, 'alt' | 'label' | 'onChange' | 'outlined'> {
    onChange?: (newChecked: boolean) => void
    checked: boolean
    label?: string | JSX.Element
    /** Whether the switch should use the alternative primary color. */
    alt?: boolean
    /** Default switches are inline. Primary switches _with a label_ are wrapped in an outlined block. */
    type?: 'default' | 'primary'
}

/** Counter used for collision-less automatic switch IDs. */
let switchCounter = 0

/** `LemonRow`-based switch component for boolean settings where the change is immediately applied.
 *
 * If part of a form, use `LemonCheckbox` instead.
 */
export function LemonSwitch({
    id: rawId,
    onChange,
    checked,
    disabled,
    loading,
    label,
    alt,
    type = 'default',
    className,
    'data-attr': dataAttr,
    ...rowProps
}: LemonSwitchProps): JSX.Element {
    const id = useMemo(() => rawId || `lemon-checkbox-${switchCounter++}`, [rawId])
    const [isActive, setIsActive] = useState(false)

    return (
        <LemonRow
            outlined={type === 'primary'}
            className={clsx('LemonSwitch', className, {
                'LemonSwitch--checked': checked,
                'LemonSwitch--active': !disabled && isActive,
                'LemonSwitch--alt': alt,
                'LemonSwitch--full-width': rowProps.fullWidth,
            })}
            disabled={disabled}
            sideIcon={
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
                    disabled={disabled}
                    data-attr={dataAttr}
                >
                    <div className="LemonSwitch__slider" />
                    <div className="LemonSwitch__handle">
                        {loading && <Spinner size="sm" type={checked ? 'inverse' : 'primary'} traceless />}
                    </div>
                </button>
            }
            relaxedIconWidth
            {...rowProps}
        >
            {label && (
                <label className="LemonSwitch__label" htmlFor={id}>
                    {label}
                </label>
            )}
        </LemonRow>
    )
}
