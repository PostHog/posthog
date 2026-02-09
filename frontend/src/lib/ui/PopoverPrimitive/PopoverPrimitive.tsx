import * as PopoverPrimitiveBase from '@radix-ui/react-popover'
import * as React from 'react'

import { cn } from 'lib/utils/css-classes'

function PopoverPrimitive({ ...props }: React.ComponentProps<typeof PopoverPrimitiveBase.Root>): JSX.Element {
    return <PopoverPrimitiveBase.Root data-slot="popover" {...props} />
}

const PopoverPrimitiveTrigger = React.forwardRef<
    React.ComponentRef<typeof PopoverPrimitiveBase.Trigger>,
    React.ComponentProps<typeof PopoverPrimitiveBase.Trigger>
>(({ ...props }, ref): JSX.Element => {
    return <PopoverPrimitiveBase.Trigger ref={ref} data-slot="popover-trigger" {...props} />
})
PopoverPrimitiveTrigger.displayName = 'PopoverPrimitiveTrigger'

function PopoverPrimitiveContent({
    className,
    align = 'center',
    sideOffset = 4,
    ...props
}: React.ComponentProps<typeof PopoverPrimitiveBase.Content>): JSX.Element {
    return (
        <PopoverPrimitiveBase.Portal>
            <PopoverPrimitiveBase.Content
                data-slot="popover-content"
                align={align}
                sideOffset={sideOffset}
                className={cn(
                    'primitive-menu-content data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 outline-hidden',
                    className
                )}
                {...props}
            />
        </PopoverPrimitiveBase.Portal>
    )
}

function PopoverPrimitiveAnchor({ ...props }: React.ComponentProps<typeof PopoverPrimitiveBase.Anchor>): JSX.Element {
    return <PopoverPrimitiveBase.Anchor data-slot="popover-anchor" {...props} />
}

export { PopoverPrimitive, PopoverPrimitiveAnchor, PopoverPrimitiveContent, PopoverPrimitiveTrigger }
