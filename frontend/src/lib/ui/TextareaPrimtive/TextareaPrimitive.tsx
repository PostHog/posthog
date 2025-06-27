import { cn } from 'lib/utils/css-classes'
import TextareaAutosize, { TextareaAutosizeProps } from 'react-textarea-autosize'
import { TextInputBaseProps, textInputVariants } from '../TextInputPrimitive/TextInputPrimitive'

type TextareaPrimitiveProps = TextareaAutosizeProps & TextInputBaseProps

export function TextareaPrimitive({className, variant, ...rest}: TextareaPrimitiveProps): JSX.Element {
    return <TextareaAutosize {...rest} className={cn(textInputVariants({ variant }), className)} />
}