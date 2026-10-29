import { Input as InputPrimitive } from '@base-ui/react/input'
import * as React from 'react'

import './input.css'
import { cn } from './lib/utils'

const Input = React.forwardRef<
    HTMLInputElement,
    Omit<React.ComponentProps<'input'>, 'size'> & {
        /** `sm` matches a default-size Button, for a field that shares a row with buttons. */
        size?: 'default' | 'sm'
    }
>(({ className, type, size = 'default', ...props }, ref) => {
        return (
            <InputPrimitive
                ref={ref}
                type={type}
                data-quill
                data-slot="input"
                data-size={size}
                className={cn('quill-input', size === 'sm' && 'quill-input--size-sm', className)}
                {...props}
            />
        )
    }
)
Input.displayName = 'Input'

export { Input }
