import { cn } from 'lib/utils/css-classes'
import TextareaAutosize, { TextareaAutosizeProps } from 'react-textarea-autosize'
import { TextInputBaseProps, textInputVariants } from '../TextInputPrimitive/TextInputPrimitive'

type TextareaPrimitiveProps = TextareaAutosizeProps &
    TextInputBaseProps & {
        error?: boolean
    }

export function TextareaPrimitive({ className, variant, error, ...rest }: TextareaPrimitiveProps): JSX.Element {
    // Ensure cursor is at the end of the textarea when it is focused
    function onFocus(e: React.FocusEvent<HTMLTextAreaElement>): void {
        e.currentTarget.setSelectionRange(e.currentTarget.value.length, e.currentTarget.value.length)
    }

    return (
        <TextareaAutosize
            onFocus={onFocus}
            {...rest}
            className={cn(textInputVariants({ variant, error: !!error }), className)}
        />
    )
}
