import './LemonInput.scss'
import React, { useRef, useState } from 'react'
import { LemonRow, LemonRowProps } from 'lib/components/LemonRow'
import clsx from 'clsx'
import { LemonButton } from 'lib/components/LemonButton'
import { IconClose, IconMagnifier } from 'lib/components/icons'

interface LemonInputPropsBase
    extends Omit<
        React.InputHTMLAttributes<HTMLInputElement>,
        'value' | 'defaultValue' | 'onChange' | 'prefix' | 'suffix'
    > {
    ref?: React.Ref<HTMLInputElement>
    id?: string
    placeholder?: string
    /** Whether there should be a clear icon to the right allowing you to reset the input. The `suffix` prop will be ignored if clearing is allowed. */
    allowClear?: boolean
    /** Icon to prefix input field */
    icon?: React.ReactElement | null
    /** Icon to suffix input field */
    sideIcon?: React.ReactElement | null
    /** Whether input field is disabled */
    disabled?: boolean
    /** Whether input field is full width */
    fullWidth?: boolean
}

interface LemonInputPropsText extends LemonInputPropsBase {
    type?: 'text' | 'email' | 'search'
    value?: string
    defaultValue?: string
    onChange?: (newValue: string) => void
    onPressEnter?: (newValue: string) => void
}

interface LemonInputPropsNumber extends LemonInputPropsBase {
    type: 'number'
    value?: number
    defaultValue?: number
    onChange?: (newValue: number) => void
    onPressEnter?: (newValue: number) => void
}

export type LemonInputProps = LemonInputPropsText | LemonInputPropsNumber

/** A `LemonRow`-based `input` component for single-line text. */
export const LemonInput = React.forwardRef<HTMLInputElement, LemonInputProps>(function _LemonInput(
    {
        className,
        onChange,
        onFocus,
        onBlur,
        onPressEnter,
        allowClear,
        fullWidth,
        icon,
        sideIcon,
        type,
        value,
        width,
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

    // Type=search has some special overrides
    allowClear = allowClear ?? (type === 'search' ? true : false)
    fullWidth = fullWidth ?? (type === 'search' ? false : true)
    icon = icon ?? (type === 'search' ? <IconMagnifier /> : undefined)
    width = width ?? (type === 'search' && !fullWidth ? 240 : undefined)

    const rowProps: LemonRowProps<'span'> = {
        tag: 'span',
        className: clsx(
            'LemonInput',
            !textProps.disabled && focused && 'LemonInput--focused',
            value && 'LemonInput--hasContent',
            className
        ),
        disabled: textProps.disabled,
        fullWidth,
        icon,
        sideIcon:
            allowClear && value ? (
                <LemonButton
                    size="small"
                    noPadding
                    icon={<IconClose />}
                    status="muted-alt"
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
                sideIcon
            ),
        onKeyDown: (event) => {
            if (onPressEnter && event.key === 'Enter') {
                if (type === 'number') {
                    onPressEnter(value ?? 0)
                } else {
                    onPressEnter(value?.toString() ?? '')
                }
            }
        },
        onClick: () => {
            focus()
        },
        outlined: true,
        style: {
            width: width,
        },
    }
    const props: React.InputHTMLAttributes<HTMLInputElement> = {
        ...textProps,
        className: 'LemonInput__input',
        onChange: (event) => {
            if (type === 'number') {
                onChange?.(event.currentTarget.valueAsNumber)
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
        value,
        type: type || 'text',
    }

    return (
        <LemonRow {...rowProps}>
            <input {...props} ref={inputRef} />
        </LemonRow>
    )
})
