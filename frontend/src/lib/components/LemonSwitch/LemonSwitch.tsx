import clsx from 'clsx'
import React, { useState } from 'react'
import { LemonRow, LemonRowProps } from '../LemonRow'
import { Spinner } from '../Spinner/Spinner'
import './LemonSwitch.scss'

export interface LemonSwitchProps {
    id?: string
    onChange: (newChecked: boolean) => void
    checked: boolean
    loading?: boolean
    label?: string | JSX.Element
    /** Whether the switch should use the alternative primary color. */
    alt?: boolean
    /** Default switches are inline. Primary switches _with a label_ are wrapped in an outlined block. */
    type?: 'default' | 'primary'
    style?: React.CSSProperties
    rowProps?: Omit<LemonRowProps<'div'>, 'className' | 'outlined'>
    disabled?: boolean
    'data-attr'?: string
}

export function LemonSwitch({
    id,
    onChange,
    checked,
    loading,
    label,
    alt,
    type = 'default',
    style,
    rowProps,
    disabled,
    'data-attr': dataAttr,
}: LemonSwitchProps): JSX.Element {
    const [isActive, setIsActive] = useState(false)

    return (
        <LemonRow
            outlined={type === 'primary'}
            className={clsx(
                'LemonSwitch',
                checked && 'LemonSwitch--checked',
                isActive && 'LemonSwitch--active',
                alt && 'LemonSwitch--alt'
            )}
            sideIcon={
                <button
                    id={id}
                    className="LemonSwitch__button"
                    type="button"
                    role="switch"
                    onClick={() => onChange(!checked)}
                    onMouseDown={() => setIsActive(true)}
                    onMouseUp={() => setIsActive(false)}
                    onMouseOut={() => setIsActive(false)}
                    style={style}
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
