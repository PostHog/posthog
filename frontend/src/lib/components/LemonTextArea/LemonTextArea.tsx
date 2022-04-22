import './LemonTextArea.scss'
import React, { useRef, useState } from 'react'
import { LemonInputPropsBase } from 'lib/components/LemonInput/LemonInput'
import { LemonRow, LemonRowProps } from 'lib/components/LemonRow'
import clsx from 'clsx'
import { LemonButton } from 'lib/components/LemonButton'
import { IconClose } from 'lib/components/icons'

export interface LemonTextAreaProps
    extends Omit<
            React.TextareaHTMLAttributes<HTMLTextAreaElement>,
            'value' | 'defaultValue' | 'onChange' | 'prefix' | 'suffix'
        >,
        LemonInputPropsBase {
    ref?: React.Ref<HTMLTextAreaElement>
}

export const LemonTextArea = React.forwardRef<HTMLTextAreaElement, LemonTextAreaProps>(function _LemonTextArea(
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
        ...textProps
    },
    ref
): JSX.Element {
    const _ref = useRef<HTMLTextAreaElement | null>(null)
    const textRef = ref || _ref
    const [focused, setFocused] = useState<boolean>(Boolean(textProps.autoFocus))

    const rowProps: LemonRowProps<'span'> = {
        tag: 'span',
        className: clsx(
            'LemonTextArea',
            textProps.disabled && 'LemonTextArea--disabled',
            !textProps.disabled && focused && 'LemonTextArea--focused',
            embedded && 'LemonTextArea--embedded',
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
                onPressEnter(textProps.value?.toString() ?? '')
            }
        },
        onClick: () => {
            if (textRef && 'current' in textRef) {
                textRef.current?.focus()
            }
            setFocused(true)
        },
        outlined: !embedded,
    }
    const props: React.TextareaHTMLAttributes<HTMLTextAreaElement> = {
        className: 'LemonTextArea__textarea',
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
        ...textProps,
    }

    return (
        <LemonRow {...rowProps}>
            <textarea rows={5} {...props} ref={textRef} />
        </LemonRow>
    )
})
