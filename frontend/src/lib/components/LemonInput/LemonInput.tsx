import './LemonInput.scss'
import React, { useRef, useState } from 'react'
import { LemonRow, LemonRowProps } from 'lib/components/LemonRow'
import clsx from 'clsx'
import { LemonButton } from 'lib/components/LemonButton'
import { IconClose } from 'lib/components/icons'

export interface LemonInputProps
    extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'onChange' | 'prefix' | 'suffix'> {
    ref?: React.Ref<HTMLInputElement>
    id?: string
    value?: string
    defaultValue?: string
    placeholder?: string
    onChange?: (newValue: string) => void
    onPressEnter?: (newValue: string) => void
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

/** Styled input */
export function LemonInputInternal({
    ref,
    className,
    onChange,
    onFocus,
    onBlur,
    onPressEnter,
    embedded = false,
    allowClear = false,
    icon,
    sideIcon,
    ...inputProps
}: LemonInputProps): JSX.Element {
    const inputRef = useRef<HTMLInputElement | null>(null)
    const [focused, setFocused] = useState<boolean>(Boolean(inputProps.autoFocus))

    const rowProps: LemonRowProps<'span'> = {
        tag: 'span',
        className: clsx(
            'LemonInput',
            inputProps.disabled && 'LemonInput--disabled',
            !inputProps.disabled && focused && 'LemonInput--focused',
            embedded && 'LemonInput--embedded',
            className
        ),
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
                }}
            />
        ) : (
            sideIcon
        ),
        onKeyDown: (event) => {
            if (onPressEnter && event.key === 'Enter') {
                onPressEnter(inputProps.value?.toString() ?? '')
            }
        },
        onClick: () => {
            inputRef?.current?.focus()
            setFocused(true)
        },
        outlined: !embedded,
    }
    const props: React.InputHTMLAttributes<HTMLInputElement> = {
        className: 'LemonInput__input',
        type: 'text',
        onChange: (event) => {
            onChange?.(event.currentTarget.value ?? '')
        },
        onFocus: (event) => {
            setFocused(true)
            onFocus?.(event)
        },
        onBlur: (event) => {
            setFocused(false)
            onBlur?.(event)
        },
        ...inputProps,
    }

    return (
        <LemonRow {...rowProps} ref={ref as React.Ref<JSX.IntrinsicElements['input']>}>
            <input {...props} ref={inputRef} />
        </LemonRow>
    )
}

export const LemonInput = React.forwardRef<HTMLInputElement, LemonInputProps>(function _LemonInputInternal(
    props,
    ref
): JSX.Element {
    return <LemonInputInternal {...props} ref={ref} />
})
