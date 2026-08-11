import { Input as InputPrimitive } from '@base-ui/react/input'
import * as React from 'react'

import './input.css'
import { cn } from './lib/utils'

/**
 * A native input element that automatically works with [Field](https://base-ui.com/react/components/field).
 * Renders an `<input>` element.
 *
 * Documentation: [Base UI Input](https://base-ui.com/react/components/input)
 *
 * @baseui Input
 */
const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<'input'>>(
    ({ className, type, ...props }, ref) => {
        return (
            <InputPrimitive
                ref={ref}
                type={type}
                data-quill
                data-slot="input"
                className={cn('quill-input', className)}
                {...props}
            />
        )
    }
)
Input.displayName = 'Input'

export { Input }
