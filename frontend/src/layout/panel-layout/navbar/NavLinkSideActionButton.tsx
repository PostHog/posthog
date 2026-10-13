import { forwardRef } from 'react'

import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

interface NavLinkSideActionButtonProps extends Omit<ButtonPrimitiveProps, 'children'> {
    icon: React.ReactNode
}

export const NavLinkSideActionButton = forwardRef<HTMLButtonElement, NavLinkSideActionButtonProps>(
    function NavLinkSideActionButton({ icon, className, ...props }, ref): JSX.Element {
        return (
            <ButtonPrimitive
                ref={ref}
                iconOnly
                isSideActionRight
                tooltipPlacement="right"
                className={cn('-outline-offset-2', className)}
                {...props}
            >
                <span className="flex text-tertiary opacity-70 group-hover/nav-link:text-primary group-hover/nav-link:opacity-100 [&>svg]:size-3">
                    {icon}
                </span>
            </ButtonPrimitive>
        )
    }
)
