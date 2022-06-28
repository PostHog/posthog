import './LemonInput.scss'
import React, { useRef, useState } from 'react'
import { LemonRow, LemonRowProps } from 'lib/components/LemonRow'
import clsx from 'clsx'
import { LemonButton } from 'lib/components/LemonButton'
import { IconClose } from 'lib/components/icons'

export interface LemonNumericInputProps
    extends Omit<
        React.InputHTMLAttributes<HTMLInputElement>,
        'value' | 'defaultValue' | 'onChange' | 'prefix' | 'suffix'
    > {
    ref?: React.Ref<HTMLInputElement>
    id?: string
    value?: number | string
    defaultValue?: string
    placeholder?: string
    onChange?: (newValue: number | string | undefined) => void
    onPressEnter?: (newValue: number | string | undefined) => void
    /** An embedded input has no border around it and no background. This way it blends better into other components. */
    embedded?: boolean
    /** Whether there should be a clear icon to the right allowing you to reset the input. The `suffix` prop will be ignored if clearing is allowed. */
    allowClear?: boolean
    /** Icon to prefix input field */
    icon?: React.ReactElement | null
    /** Icon to suffix input field */
    sideIcon?: React.ReactElement | null
    /** Whether input field is disabled */
    disabled?: boolean
}

/** A `LemonRow`-based `input` component for numberic inputs. */
export const LemonNumericInput = React.forwardRef<HTMLInputElement, LemonNumericInputProps>(function _LemonNumericInput(
    {
        className,
        onChange,
        onFocus,
        onBlur,
        onPressEnter,
        embedded = false,
        allowClear = false,
        icon,
        sideIcon,
        ...props
    },
    ref
): JSX.Element {
    const _ref = useRef<HTMLInputElement | null>(null)
    const inputRef = ref || _ref
    const [focused, setFocused] = useState<boolean>(Boolean(props.autoFocus))

    const focus = (): void => {
        if (inputRef && 'current' in inputRef) {
            inputRef.current?.focus()
        }
        setFocused(true)
    }

    const rowProps: LemonRowProps<'span'> = {
        tag: 'span',
        className: clsx(
            'LemonInput',
            !props.disabled && focused && 'LemonInput--focused',
            embedded && 'LemonInput--embedded',
            className
        ),
        disabled: props.disabled,
        fullWidth: true,
        icon,
        sideIcon: allowClear ? (
            <LemonButton
                type="tertiary"
                icon={<IconClose style={{ fontSize: '1rem' }} />}
                tooltip="Clear input"
                onClick={(e) => {
                    e.stopPropagation()
                    onChange?.('')
                    focus()
                }}
            />
        ) : (
            sideIcon
        ),
        onKeyDown: (event) => {
            if (onPressEnter && event.key === 'Enter') {
                onPressEnter(props.value)
            }
        },
        onClick: () => {
            focus()
        },
        outlined: !embedded,
    }
    const inputProps: React.InputHTMLAttributes<HTMLInputElement> = {
        className: 'LemonInput__input',
        type: 'number',
        onChange: (event) => {
            onChange?.(isNaN(event.currentTarget.valueAsNumber) ? '' : event.currentTarget.valueAsNumber)
        },
        onFocus: (event) => {
            setFocused(true)
            onFocus?.(event)
        },
        onBlur: (event) => {
            setFocused(false)
            onBlur?.(event)
        },
        ...props,
    }

    return (
        <LemonRow {...rowProps}>
            <input {...inputProps} ref={inputRef} />
        </LemonRow>
    )
})
