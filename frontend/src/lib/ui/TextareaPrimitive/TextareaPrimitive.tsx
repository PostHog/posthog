import { forwardRef } from 'react'
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
        // Ensure cursor is at the end of the textarea when it is focused
        function onFocus(e: React.FocusEvent<HTMLTextAreaElement>): void {
            e.currentTarget.setSelectionRange(e.currentTarget.value.length, e.currentTarget.value.length)
        }

        return (
            <div className={cn('relative flex flex-col gap-0', wrapperClassName)}>
                <TextareaAutosize
                    ref={ref}
                    onFocus={onFocus}
                    aria-label={markdown ? 'Markdown supported' : undefined}
                    {...rest}
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
