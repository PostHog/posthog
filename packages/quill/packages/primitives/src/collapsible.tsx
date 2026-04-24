import { Collapsible as CollapsiblePrimitive } from '@base-ui/react/collapsible'
import { ChevronDownIcon, ChevronUpIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { cn } from './lib/utils'

type CollapsibleVariant = 'default' | 'folder'

const CollapsibleVariantContext = React.createContext<CollapsibleVariant>('default')

type CollapsibleProps = CollapsiblePrimitive.Root.Props & {
    variant?: CollapsibleVariant
}

function Collapsible({ variant = 'default', className, ...props }: CollapsibleProps): React.ReactElement {
    return (
        <CollapsibleVariantContext.Provider value={variant}>
            <CollapsiblePrimitive.Root
                data-quill
                data-slot="collapsible"
                data-variant={variant}
                className={cn(
                    'group/collapsible',
                    variant !== 'folder' && 'hover:bg-muted data-open:bg-muted rounded-sm',
                    className
                )}
                {...props}
            />
        </CollapsibleVariantContext.Provider>
    )
}

function CollapsibleTrigger({
    children,
    className,
    ...props
}: CollapsiblePrimitive.Trigger.Props): React.ReactElement {
    const variant = React.useContext(CollapsibleVariantContext)
    const chevrons = (
        <>
            <ChevronDownIcon
                data-slot="collapsible-trigger-icon"
                className="pointer-events-none shrink-0 group-data-[panel-open]/collapsible-trigger:hidden"
            />
            <ChevronUpIcon
                data-slot="collapsible-trigger-icon"
                className="pointer-events-none hidden shrink-0 group-data-[panel-open]/collapsible-trigger:inline"
            />
        </>
    )
    return (
        <CollapsiblePrimitive.Trigger
            data-slot="collapsible-trigger"
            data-variant={variant}
            className={cn(
                `w-full group/collapsible-trigger aria-expanded:bg-fill-selected px-2 flex items-center gap-2 text-xs/relaxed **:data-[slot=collapsible-trigger-icon]:size-4 **:data-[slot=collapsible-trigger-icon]:text-muted-foreground justify-start`,
                variant !== 'folder' && 'aria-expanded:bg-transparent',
                className
            )}
            render={<Button size="sm"/>}
            {...props}
        >
            {variant === 'folder' && chevrons}
            {children}
            {variant === 'default' && chevrons}
        </CollapsiblePrimitive.Trigger>
    )
}

function CollapsibleContent({ children, className, ...props }: CollapsiblePrimitive.Panel.Props): React.ReactElement {
    const variant = React.useContext(CollapsibleVariantContext)

    return (
        <CollapsiblePrimitive.Panel
            data-slot="collapsible-content"
            className="h-[var(--collapsible-panel-height)] overflow-hidden transition-[height] duration-200 ease-out data-[starting-style]:h-0 data-[ending-style]:h-0 relative z-1"
            {...props}
        >
            <div
                className={cn(
                    'px-2 pt-0 pb-2 [&_a]:underline [&_a]:underline-offset-3 [&_a]:hover:text-foreground [&_p:not(:last-child)]:mb-4',
                    variant === 'folder' && 'pr-0',
                    className
                )}
            >
                {children}
            </div>
        </CollapsiblePrimitive.Panel>
    )
}

export { Collapsible, CollapsibleTrigger, CollapsibleContent }
