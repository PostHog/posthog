import { forwardRef, useRef } from 'react'
import TextareaAutosize, { TextareaAutosizeProps } from 'react-textarea-autosize'

import { IconMarkdownFilled } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { ButtonPrimitive } from '../Button/ButtonPrimitives'
import { TextInputBaseProps, textInputVariants } from '../TextInputPrimitive/TextInputPrimitive'

type TextareaPrimitiveProps = TextareaAutosizeProps &
    TextInputBaseProps & {
        error?: boolean
        markdown?: boolean
        wrapperClassName?: string
    }

export const TextareaPrimitive = forwardRef<HTMLTextAreaElement, TextareaPrimitiveProps>(
    ({ className, variant, error, markdown = false, wrapperClassName, ...rest }, ref): JSX.Element => {
        const focusFollowsPointerRef = useRef(false)

        // Put the cursor at the end when focus arrives without a pointer press, e.g. autofocus or tab.
        // After a pointer press the caret must stay where it landed, so that click and drag selects text.
        function onFocus(e: React.FocusEvent<HTMLTextAreaElement>): void {
            if (!focusFollowsPointerRef.current) {
                e.currentTarget.setSelectionRange(e.currentTarget.value.length, e.currentTarget.value.length)
            }
            focusFollowsPointerRef.current = false
            rest.onFocus?.(e)
        }

        function onPointerDown(e: React.PointerEvent<HTMLTextAreaElement>): void {
            focusFollowsPointerRef.current = true
            rest.onPointerDown?.(e)
        }

        function onBlur(e: React.FocusEvent<HTMLTextAreaElement>): void {
            focusFollowsPointerRef.current = false
            rest.onBlur?.(e)
        }

        return (
            <div className={cn('relative flex flex-col gap-0', wrapperClassName)}>
                <TextareaAutosize
                    ref={ref}
                    aria-label={markdown ? 'Markdown supported' : undefined}
                    {...rest}
                    onFocus={onFocus}
                    onPointerDown={onPointerDown}
                    onBlur={onBlur}
                    className={cn(
                        textInputVariants({ variant, error: !!error, size: 'auto' }),
                        'resize-y show-scrollbar-on-hover px-[var(--button-padding-x-base)] py-[var(--button-padding-y-base)]',
                        className
                    )}
                />
                {markdown && (
                    <ButtonPrimitive
                        className="absolute bottom-1 right-1"
                        tooltip="Markdown supported"
                        tooltipPlacement="top"
                        inert
                        size="xs"
                        iconOnly
                        aria-hidden
                    >
                        <IconMarkdownFilled className="text-tertiary size-4" />
                    </ButtonPrimitive>
                )}
            </div>
        )
    }
)
