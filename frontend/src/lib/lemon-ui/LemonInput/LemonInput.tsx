import './LemonInput.scss'
import React, { useRef, useState } from 'react'
import clsx from 'clsx'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconClose, IconEyeHidden, IconEyeVisible, IconMagnifier } from 'lib/lemon-ui/icons'

type LemonInputPropsBase = Pick<
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
> & {
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
    'data-attr'?: string
    'aria-label'?: string
}

type LemonInputPropsText = LemonInputPropsBase & {
    type?: 'text' | 'email' | 'search' | 'url' | 'password'
    value?: string
    defaultValue?: string
    onChange?: (newValue: string) => void
    onPressEnter?: (newValue: string) => void
}

type LemonInputPropsNumber = LemonInputPropsBase &
    Pick<React.InputHTMLAttributes<HTMLInputElement>, 'step' | 'min' | 'max'> & {
        type: 'number'
        value?: number
        defaultValue?: number
        onChange?: (newValue: number | undefined) => void
        onPressEnter?: (newValue: number | undefined) => void
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
        allowClear = false,
        fullWidth = false,
        prefix,
        suffix,
        type,
        value,
        transparentBackground = false,
        size = 'medium',
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

    // Type=search has some special overrides
    allowClear = allowClear ?? (type === 'search' ? true : false)
    fullWidth = fullWidth ?? (type === 'search' ? false : true)
    prefix = prefix ?? (type === 'search' ? <IconMagnifier /> : undefined)
    // Type=password has some special overrides
    suffix =
        suffix ??
        (type === 'password' ? (
            <LemonButton
                size="small"
                noPadding
                icon={passwordVisible ? <IconEyeHidden /> : <IconEyeVisible />}
                status="primary-alt"
                tooltip={passwordVisible ? 'Hide password' : 'Show password'}
                onClick={(e) => {
                    e.stopPropagation()
                    focus()
                    setPasswordVisible(!passwordVisible)
                }}
            />
        ) : undefined)

    // allowClear button takes precedence if set
    suffix =
        allowClear && value ? (
            <LemonButton
                size="small"
                icon={<IconClose />}
                status="primary-alt"
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
        ) : (
            suffix
        )

    return (
        <span
            className={clsx(
                'LemonInput',
                status !== 'default' && `LemonInput--status-${status}`,
                type && `LemonInput--type-${type}`,
                size && `LemonInput--${size}`,
                textProps.disabled && 'LemonInput--disabled',
                fullWidth && 'LemonInput--full-width',
                value && 'LemonInput--has-content',
                !textProps.disabled && focused && 'LemonInput--focused',
                transparentBackground && 'LemonInput--transparent-background',
                className
            )}
            onKeyDown={(event) => {
                if (onPressEnter && event.key === 'Enter') {
                    if (type === 'number') {
                        onPressEnter(value ?? 0)
                    } else {
                        onPressEnter(value?.toString() ?? '')
                    }
                }
            }}
            onClick={() => focus()}
        >
            {prefix}
            <input
                className="LemonInput__input"
                ref={inputRef}
                type={(type === 'password' && passwordVisible ? 'text' : type) || 'text'}
                value={value}
                onChange={(event) => {
                    if (type === 'number') {
                        onChange?.(
                            !isNaN(event.currentTarget.valueAsNumber) ? event.currentTarget.valueAsNumber : undefined
                        )
                    } else {
                        onChange?.(event.currentTarget.value ?? '')
                    }
                }}
                onFocus={(event) => {
                    setFocused(true)
                    onFocus?.(event)
                }}
                onBlur={(event) => {
                    setFocused(false)
                    onBlur?.(event)
                }}
                {...textProps}
            />
            {suffix}
        </span>
    )
})
