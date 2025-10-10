import './LemonInput.scss'

import { useMergeRefs } from '@floating-ui/react'
import clsx from 'clsx'
import React, { useRef, useState } from 'react'

import { IconEye, IconSearch, IconX } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconEyeHidden } from 'lib/lemon-ui/icons'

import { RawInputAutosize } from './RawInputAutosize'

interface LemonInputPropsBase
    extends Pick<
        // NOTE: We explicitly pick rather than omit to ensure these components aren't used incorrectly
        React.InputHTMLAttributes<HTMLInputElement>,
        | 'className'
        | 'onClick'
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
        | 'pattern'
    > {
    inputRef?: React.Ref<HTMLInputElement>
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
    /** @deprecated Use `disabledReason` instead and provide a reason. */
    disabled?: boolean
    /** Like plain `disabled`, except we enforce a reason to be shown in the tooltip. */
    disabledReason?: string | null | false
    /** Whether input field is full width. Cannot be used in conjuction with `autoWidth`. */
    fullWidth?: boolean
    /** Whether input field should be as wide as its content. Cannot be used in conjuction with `fullWidth`. */
    autoWidth?: boolean
    /** Special case - show a transparent background rather than white */
    transparentBackground?: boolean
    /** Size of the element. Default: `'medium'`. */
    size?: 'xsmall' | 'small' | 'medium' | 'large'
    onPressEnter?: (event: React.KeyboardEvent<HTMLInputElement>) => void
    'data-attr'?: string
    'aria-label'?: string
    /** Whether to stop propagation of events from the input */
    stopPropagation?: boolean
}

export interface LemonInputPropsText extends LemonInputPropsBase {
    type?: 'text' | 'email' | 'search' | 'url' | 'password' | 'time'
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

export const LemonInput = React.forwardRef<HTMLDivElement, LemonInputProps>(function LemonInput(
    {
        className,
        onChange,
        onFocus,
        onBlur,
        onPressEnter,
        status = 'default',
        allowClear, // Default handled inside the component
        fullWidth,
        autoWidth,
        prefix,
        suffix,
        type,
        value,
        transparentBackground = false,
        size = 'medium',
        stopPropagation = false,
        inputRef,
        disabled,
        disabledReason,
        ...props
    },
    ref
): JSX.Element {
    const internalInputRef = useRef<HTMLInputElement>(null)
    const mergedInputRef = useMergeRefs([inputRef, internalInputRef])

    const [focused, setFocused] = useState<boolean>(Boolean(props.autoFocus))
    const [passwordVisible, setPasswordVisible] = useState<boolean>(false)

    if (autoWidth && fullWidth) {
        throw new Error('Cannot use `autoWidth` and `fullWidth` props together')
    }

    const focus = (): void => {
        internalInputRef.current?.focus()
        setFocused(true)
    }

    if (type === 'search') {
        allowClear = allowClear ?? true
        prefix = prefix ?? <IconSearch />
    } else if (type === 'password') {
        const showPasswordButton = (
            <LemonButton
                size="small"
                noPadding
                icon={passwordVisible ? <IconEyeHidden /> : <IconEye />}
                tooltip={passwordVisible ? 'Hide password' : 'Show password'}
                onClick={(e) => {
                    e.stopPropagation()
                    focus()
                    setPasswordVisible(!passwordVisible)
                }}
            />
        )
        if (suffix) {
            suffix = (
                <>
                    {showPasswordButton}
                    {suffix}
                </>
            )
        } else {
            suffix = showPasswordButton
        }
    }
    // allowClear button takes precedence if set
    if (allowClear && value) {
        suffix = (
            <LemonButton
                size="small"
                noPadding
                icon={<IconX />}
                tooltip="Clear input"
                onClick={(e) => {
                    if (stopPropagation) {
                        e.stopPropagation()
                    }
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

    const InputComponent = autoWidth ? RawInputAutosize : 'input'

    return (
        <Tooltip title={disabledReason ?? undefined}>
            <span
                className={clsx(
                    'LemonInput',
                    status !== 'default' && `LemonInput--status-${status}`,
                    type && `LemonInput--type-${type}`,
                    size && `LemonInput--${size}`,
                    fullWidth && 'LemonInput--full-width',
                    value && 'LemonInput--has-content',
                    !disabled && !disabledReason && focused && 'LemonInput--focused',
                    transparentBackground && 'LemonInput--transparent-background',
                    className
                )}
                aria-disabled={disabled || !!disabledReason}
                onClick={() => focus()}
                ref={ref}
            >
                {prefix}
                <InputComponent
                    className="LemonInput__input"
                    ref={mergedInputRef}
                    type={(type === 'password' && passwordVisible ? 'text' : type) || 'text'}
                    value={value}
                    disabled={disabled || !!disabledReason}
                    onChange={(event) => {
                        if (stopPropagation) {
                            event.stopPropagation()
                        }
                        if (type === 'number') {
                            onChange?.(event.currentTarget.valueAsNumber)
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
                    {...props}
                />
                {suffix}
            </span>
        </Tooltip>
    )
})
