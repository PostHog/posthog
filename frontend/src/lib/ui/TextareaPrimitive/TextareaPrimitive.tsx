import { cn } from 'lib/utils/css-classes'
import TextareaAutosize, { TextareaAutosizeProps } from 'react-textarea-autosize'
import { TextInputBaseProps, textInputVariants } from '../TextInputPrimitive/TextInputPrimitive'
import { forwardRef } from 'react'
import { IconMarkdown } from 'lib/lemon-ui/icons/icons'
import { ButtonPrimitive } from '../Button/ButtonPrimitives'

type TextareaPrimitiveProps = TextareaAutosizeProps &
    TextInputBaseProps & {
        error?: boolean
        markdown?: boolean
    }

export const TextareaPrimitive = forwardRef<HTMLTextAreaElement, TextareaPrimitiveProps>(
    ({ className, variant, error, markdown = false, ...rest }, ref): JSX.Element => {
        // Ensure cursor is at the end of the textarea when it is focused
        function onFocus(e: React.FocusEvent<HTMLTextAreaElement>): void {
            e.currentTarget.setSelectionRange(e.currentTarget.value.length, e.currentTarget.value.length)
        }

        return (
            <div className="relative flex flex-col gap-0">
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
                        <IconMarkdown className="text-tertiary size-4" />
                    </ButtonPrimitive>
                )}
            </div>
        )
    }
)
