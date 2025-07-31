import { cn } from 'lib/utils/css-classes'
import TextareaAutosize, { TextareaAutosizeProps } from 'react-textarea-autosize'
import { TextInputBaseProps, textInputVariants } from '../TextInputPrimitive/TextInputPrimitive'
import { forwardRef } from 'react'

type TextareaPrimitiveProps = TextareaAutosizeProps &
    TextInputBaseProps & {
        error?: boolean
    }

export const TextareaPrimitive = forwardRef<HTMLTextAreaElement, TextareaPrimitiveProps>(
    ({ className, variant, error, ...rest }, ref): JSX.Element => {
        // Ensure cursor is at the end of the textarea when it is focused
        function onFocus(e: React.FocusEvent<HTMLTextAreaElement>): void {
            e.currentTarget.setSelectionRange(e.currentTarget.value.length, e.currentTarget.value.length)
        }

        return (
            <TextareaAutosize
                ref={ref}
                onFocus={onFocus}
                {...rest}
                className={cn(
                    textInputVariants({ variant, error: !!error }),
                    'h-auto show-scrollbar-on-hover px-[var(--button-padding-x-base)] py-[var(--button-padding-y-base)]',
                    className
                )}
            />
        )
    }
)
