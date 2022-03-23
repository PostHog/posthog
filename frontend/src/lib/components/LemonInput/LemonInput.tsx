import './LemonInput.scss'
import React from 'react'
import { LemonRow, LemonRowProps, LemonRowPropsBase } from 'lib/components/LemonRow'
import clsx from 'clsx'
import { LemonButton } from 'lib/components/LemonButton'
import { IconClose, IconMagnifier } from 'lib/components/icons'

export interface LemonInputProps extends Omit<LemonRowPropsBase<'input'>, 'tag' | 'prefix' | 'ref' | 'onChange'> {
    ref?: React.Ref<HTMLButtonElement>
    type?: 'default' | 'stealth'
    htmlType?: LemonRowPropsBase<'input'>['type']
    value?: string
    onChange?: (newValue: string) => void
    onPressEnter?: (newValue: string) => void
    allowClear?: boolean
    /** The initial input content */
    defaultValue?: string
    /** Whether the input is disabled */
    disabled?: boolean
    /** The ID for input */
    id?: string
    /** The max length */
    maxLength?: number
}

/** Styled input */
function LemonInputInternal(
    { type = 'default', htmlType = 'text', className, onChange, onPressEnter, allowClear, ...props }: LemonInputProps,
    ref: React.Ref<JSX.IntrinsicElements['input']>
): JSX.Element {
    const rowProps: LemonRowProps<'span'> = {
        tag: 'span',
        className: clsx('LemonInput', type !== 'default' && `LemonInput--${type}`, className),
        icon: <IconMagnifier className={clsx('magnifier-icon', props.value && 'magnifier-icon-active')} />,
    }
    const inputProps: LemonRowProps<'input'> = {
        type: htmlType,
        onChange: (event) => {
            onChange?.(event.currentTarget.value?.toString() ?? '')
        },
        onKeyDown: (event) => {
            if (onPressEnter && event.key === 'Enter') {
                onPressEnter(event.currentTarget.value?.toString() ?? '')
            }
        },
        ...props,
    }
    if (allowClear) {
        rowProps.sideIcon = (
            <LemonButton
                className="LemonInput__side-button"
                type="tertiary"
                icon={<IconClose style={{ fontSize: 16 }} />}
                tooltip="Clear selection"
                onClick={(e) => {
                    e.stopPropagation()
                    onChange?.('')
                }}
            />
        )
    }

    return (
        <LemonRow {...rowProps}>
            <input {...inputProps} ref={ref} />
        </LemonRow>
    )
}

export const LemonInput = React.forwardRef(LemonInputInternal) as typeof LemonInputInternal
