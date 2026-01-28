import './LemonInput.scss'

import { useMergeRefs } from '@floating-ui/react'
import clsx from 'clsx'
import React, { useRef, useState } from 'react'

import { IconEye, IconSearch, IconX } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
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
    disabledReason?: React.ReactNode | null | false
    /** Whether the disabled reason tooltip is interactive (e.g., contains a link) */
    disabledReasonInteractive?: boolean
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
    /** Small label shown above the top-right corner, e.g. "last used" */
    badgeText?: string
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

// Delay for interactive tooltips to close after mouse leave.
// This allows some grace period in case the user moves the
// cursor out of the tooltip briefly while intending to
// interact with it.
export const INTERACTIVE_CLOSE_DELAY_MS = 750

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
        disabledReasonInteractive,
        badgeText,
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
                    if (onChange) {
                        if (type === 'number') {
                            // @ts-expect-error - onChange is typed as never, force it to match the right one
                            onChange(0)
                        } else {
                            // @ts-expect-error - onChange is typed as never, force it to match the right one
                            onChange('')
                        }
                    }

                    focus()
                }}
            />
        )
    }

    const InputComponent = autoWidth ? RawInputAutosize : 'input'
    return (
        <Tooltip
            title={disabledReason ?? undefined}
            interactive={disabledReasonInteractive}
            closeDelayMs={disabledReasonInteractive ? INTERACTIVE_CLOSE_DELAY_MS : undefined}
        >
            <span
                className={clsx(
                    'LemonInput',
                    'input-like',
                    status !== 'default' && `LemonInput--status-${status}`,
                    type && `LemonInput--type-${type}`,
                    size && `LemonInput--${size}`,
                    fullWidth && 'LemonInput--full-width',
                    value && 'LemonInput--has-content',
                    !disabled && !disabledReason && focused && 'LemonInput--focused',
                    transparentBackground && 'LemonInput--transparent-background',
                    badgeText && 'relative',
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

                        if (onChange) {
                            if (type === 'number') {
                                // @ts-expect-error - onChange is typed as never, force it to match the right one
                                onChange(event.currentTarget.valueAsNumber)
                            } else {
                                // @ts-expect-error - onChange is typed as never, force it to match the right one
                                onChange(event.currentTarget.value ?? '')
                            }
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
                {badgeText && (
                    <LemonTag className="absolute -top-3 -right-2 pointer-events-none" size="small" type="muted">
                        {badgeText}
                    </LemonTag>
                )}
            </span>
        </Tooltip>
    )
})
