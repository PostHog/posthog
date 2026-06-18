import { Input as InputPrimitive } from '@base-ui/react/input'
import * as React from 'react'

import './input.css'
import { cn } from './lib/utils'

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
