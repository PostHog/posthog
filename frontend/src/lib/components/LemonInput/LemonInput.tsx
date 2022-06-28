import './LemonInput.scss'
import React, { useRef, useState } from 'react'
import { LemonRow, LemonRowProps } from 'lib/components/LemonRow'
import clsx from 'clsx'
import { LemonButton } from 'lib/components/LemonButton'
import { IconClose } from 'lib/components/icons'

export interface LemonInputProps
    extends Omit<
        React.InputHTMLAttributes<HTMLInputElement>,
        'value' | 'defaultValue' | 'onChange' | 'prefix' | 'suffix'
    > {
    ref?: React.Ref<HTMLInputElement>
    id?: string
    type?: string
    value?: string | number
    defaultValue?: string
    placeholder?: string
    onChange?: (newValue: string | number) => void
    onPressEnter?: (newValue: string | number) => void
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

/** A `LemonRow`-based `input` component for single-line text. */
export const LemonInput = React.forwardRef<HTMLInputElement, LemonInputProps>(function _LemonInput(
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
        type,
        ...textProps
    },
    ref
): JSX.Element {
    const _ref = useRef<HTMLInputElement | null>(null)
    const inputRef = ref || _ref
    const [focused, setFocused] = useState<boolean>(Boolean(textProps.autoFocus))

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
            !textProps.disabled && focused && 'LemonInput--focused',
            embedded && 'LemonInput--embedded',
            className
        ),
        disabled: textProps.disabled,
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
                onPressEnter(textProps.value?.toString() ?? '')
            }
        },
        onClick: () => {
            focus()
        },
        outlined: !embedded,
    }
    const props: React.InputHTMLAttributes<HTMLInputElement> = {
        className: 'LemonInput__input',
        type: 'text',
        onChange: (event) => {
            if (type === 'number') {
                onChange?.(isNaN(event.currentTarget.valueAsNumber) ? '' : event.currentTarget.valueAsNumber)
            } else {
                onChange?.(event.currentTarget.value ?? '')
            }
        },
        onFocus: (event) => {
            setFocused(true)
            onFocus?.(event)
        },
        onBlur: (event) => {
            setFocused(false)
            onBlur?.(event)
        },
        ...textProps,
    }

    return (
        <LemonRow {...rowProps}>
            <input {...props} ref={inputRef} />
        </LemonRow>
    )
})

export const LemonNumericInput = React.forwardRef<HTMLInputElement, LemonInputProps>(function _LemonInput(
    props,
    ref
): JSX.Element {
    return <LemonInput type="number" {...props} ref={ref} />
})
