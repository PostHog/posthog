import './LemonTextArea.scss'

import clsx from 'clsx'
import React, { useRef } from 'react'
import TextareaAutosize from 'react-textarea-autosize'

interface LemonTextAreaPropsBase
    extends Pick<
        React.TextareaHTMLAttributes<HTMLTextAreaElement>,
        'onFocus' | 'onBlur' | 'maxLength' | 'autoFocus' | 'onKeyDown'
    > {
    id?: string
    value?: string
    defaultValue?: string
    placeholder?: string
    className?: string
    /** Whether input field is disabled */
    disabled?: boolean
    ref?: React.Ref<HTMLTextAreaElement>
    onChange?: (newValue: string) => void
    minRows?: number
    maxRows?: number
    rows?: number
    /** Whether to stop propagation of events from the input */
    stopPropagation?: boolean
    'data-attr'?: string
}

interface LemonTextAreaWithCmdEnterProps extends LemonTextAreaPropsBase {
    /** Callback for when Cmd/Ctrl + Enter is pressed. In this case, the user adds new lines with Enter like always. */
    onPressCmdEnter?: (currentValue: string) => void
    onPressEnter?: never
}

interface LemonTextAreaWithEnterProps extends LemonTextAreaPropsBase {
    /** Callback for when Enter is pressed. In this case, to add a new line the user must press Cmd + Enter. */
    onPressEnter: (currentValue: string) => void
    onPressCmdEnter?: never
}
export type LemonTextAreaProps = LemonTextAreaWithEnterProps | LemonTextAreaWithCmdEnterProps

/** A `textarea` component for multi-line text. */
export const LemonTextArea = React.forwardRef<HTMLTextAreaElement, LemonTextAreaProps>(function _LemonTextArea(
    { className, onChange, onPressEnter, onPressCmdEnter, minRows = 3, onKeyDown, stopPropagation, ...textProps },
    ref
): JSX.Element {
    const _ref = useRef<HTMLTextAreaElement | null>(null)
    const textRef = ref || _ref

    return (
        <TextareaAutosize
            minRows={minRows}
            ref={textRef}
            className={clsx('LemonTextArea', className)}
            onKeyDown={(e) => {
                if (stopPropagation) {
                    e.stopPropagation()
                }
                if (e.key === 'Enter') {
                    const target = e.currentTarget
                    // When shift is pressed, we always just want to add a new line
                    if (!e.shiftKey) {
                        if ((e.metaKey || e.ctrlKey) && onPressCmdEnter) {
                            onPressCmdEnter(target.value)
                            e.preventDefault()
                        } else if (onPressEnter) {
                            onPressEnter(target.value)
                            e.preventDefault()
                        }
                    }
                }
                onKeyDown?.(e)
            }}
            onChange={(event) => {
                if (stopPropagation) {
                    event.stopPropagation()
                }
                return onChange?.(event.currentTarget.value ?? '')
            }}
            {...textProps}
        />
    )
})
