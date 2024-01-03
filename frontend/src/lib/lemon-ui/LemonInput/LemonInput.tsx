import './LemonInput.scss'

import clsx from 'clsx'
import { IconClose, IconEyeHidden, IconEyeVisible, IconMagnifier } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import React, { useRef, useState } from 'react'

interface LemonInputPropsBase
    extends Pick<
        // NOTE: We explicitly pick rather than omit to ensure thes components aren't used incorrectly
        React.InputHTMLAttributes<HTMLInputElement>,
        | 'className'
        | 'onFocus'
        | 'onBlur'
        | 'autoFocus'
        | 'maxLength'
        | 'onKeyDown'
        | 'onKeyUp'
        | 'onKeyPress'
        | 'autoComplete'
        | 'autoCorrect'
        | 'autoCapitalize'
        | 'spellCheck'
        | 'inputMode'
    > {
    ref?: React.Ref<HTMLInputElement>
    id?: string
    placeholder?: string
    /** Use the danger status for invalid input. */
    status?: 'default' | 'danger'
    /** Whether there should be a clear icon to the right allowing you to reset the input. The `suffix` prop will be ignored if clearing is allowed. */
    allowClear?: boolean
    /** Element to prefix input field */
    prefix?: React.ReactElement | null
    /** Element to suffix input field */
    suffix?: React.ReactElement | null
    /** Whether input field is disabled */
    disabled?: boolean
    /** Whether input field is full width */
    fullWidth?: boolean
    /** Special case - show a transparent background rather than white */
    transparentBackground?: boolean
    /** Size of the element. Default: `'medium'`. */
    size?: 'small' | 'medium'
    onPressEnter?: (event: React.KeyboardEvent<HTMLInputElement>) => void
    'data-attr'?: string
    'aria-label'?: string
    /** Whether to stop propagation of events from the input */
    stopPropagation?: boolean
}

export interface LemonInputPropsText extends LemonInputPropsBase {
    type?: 'text' | 'email' | 'search' | 'url' | 'password'
    value?: string
    defaultValue?: string
    onChange?: (newValue: string) => void
}

export interface LemonInputPropsNumber
    extends LemonInputPropsBase,
        Pick<React.InputHTMLAttributes<HTMLInputElement>, 'step' | 'min' | 'max'> {
    type: 'number'
    value?: number
    defaultValue?: number
    onChange?: (newValue: number | undefined) => void
}

export type LemonInputProps = LemonInputPropsText | LemonInputPropsNumber

export const LemonInput = React.forwardRef<HTMLInputElement, LemonInputProps>(function _LemonInput(
    {
        className,
        onChange,
        onFocus,
        onBlur,
        onPressEnter,
        status = 'default',
        allowClear, // Default handled inside the component
        fullWidth,
        prefix,
        suffix,
        type,
        value,
        transparentBackground = false,
        size = 'medium',
        stopPropagation = false,
        ...textProps
    },
    ref
): JSX.Element {
    const _ref = useRef<HTMLInputElement | null>(null)
    const inputRef = ref || _ref
    const [focused, setFocused] = useState<boolean>(Boolean(textProps.autoFocus))
    const [passwordVisible, setPasswordVisible] = useState<boolean>(false)

    const focus = (): void => {
        if (inputRef && 'current' in inputRef) {
            inputRef.current?.focus()
        }
        setFocused(true)
    }

    if (type === 'search') {
        allowClear = allowClear ?? true
        prefix = prefix ?? <IconMagnifier />
    } else if (type === 'password') {
        suffix = suffix ?? (
            <LemonButton
                size="small"
                noPadding
                icon={passwordVisible ? <IconEyeHidden /> : <IconEyeVisible />}
                tooltip={passwordVisible ? 'Hide password' : 'Show password'}
                onClick={(e) => {
                    e.stopPropagation()
                    focus()
                    setPasswordVisible(!passwordVisible)
                }}
            />
        )
    }
    // allowClear button takes precedence if set
    if (allowClear && value) {
        suffix = (
            <LemonButton
                size="small"
                noPadding
                icon={<IconClose />}
                tooltip="Clear input"
                onClick={(e) => {
                    e.stopPropagation()
                    if (type === 'number') {
                        onChange?.(0)
                    } else {
                        onChange?.('')
                    }
                    focus()
                }}
            />
        )
    }

    return (
        <span
            className={clsx(
                'LemonInput',
                status !== 'default' && `LemonInput--status-${status}`,
                type && `LemonInput--type-${type}`,
                size && `LemonInput--${size}`,
                fullWidth && 'LemonInput--full-width',
                value && 'LemonInput--has-content',
                !textProps.disabled && focused && 'LemonInput--focused',
                transparentBackground && 'LemonInput--transparent-background',
                className
            )}
            aria-disabled={textProps.disabled}
            onClick={() => focus()}
        >
            {prefix}
            <input
                className="LemonInput__input"
                ref={inputRef}
                type={(type === 'password' && passwordVisible ? 'text' : type) || 'text'}
                value={value}
                onChange={(event) => {
                    if (stopPropagation) {
                        event.stopPropagation()
                    }
                    if (type === 'number') {
                        onChange?.(
                            !isNaN(event.currentTarget.valueAsNumber) ? event.currentTarget.valueAsNumber : undefined
                        )
                    } else {
                        onChange?.(event.currentTarget.value ?? '')
                    }
                }}
                onFocus={(event) => {
                    if (stopPropagation) {
                        event.stopPropagation()
                    }
                    setFocused(true)
                    onFocus?.(event)
                }}
                onBlur={(event) => {
                    if (stopPropagation) {
                        event.stopPropagation()
                    }
                    setFocused(false)
                    onBlur?.(event)
                }}
                onKeyDown={(event) => {
                    if (stopPropagation) {
                        event.stopPropagation()
                    }
                    if (onPressEnter && event.key === 'Enter') {
                        onPressEnter(event)
                    }
                }}
                {...textProps}
            />
            {suffix}
        </span>
    )
})
