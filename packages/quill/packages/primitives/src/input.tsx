import { Input as InputPrimitive } from '@base-ui/react/input'
import * as React from 'react'

import { cn } from './lib/utils'

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<'input'>>(
    ({ className, type, ...props }, ref) => {
        return (
            <InputPrimitive
                ref={ref}
                type={type}
                data-slot="input"
                className={cn(
                    'h-8 w-full min-w-0 rounded-md border border-input bg-input/20 dark:bg-input/30 px-2 py-0.5 text-xs transition-colors outline-none file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-xs/relaxed file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:border-ring/50 focus-visible:ring-3 focus-visible:ring-ring/30 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:bg-destructive/50 aria-invalid:border-destructive-foreground/30 focus-visible:aria-invalid:ring-3 aria-invalid:ring-destructive-foreground/50 ',
                    className
                )}
                {...props}
            />
        )
    }
)
Input.displayName = 'Input'

export { Input }
