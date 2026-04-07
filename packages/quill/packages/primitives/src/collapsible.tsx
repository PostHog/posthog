import { Collapsible as CollapsiblePrimitive } from '@base-ui/react/collapsible'
import { ChevronDownIcon, ChevronUpIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { cn } from './lib/utils'

function Collapsible({ ...props }: CollapsiblePrimitive.Root.Props): React.ReactElement {
    return <CollapsiblePrimitive.Root data-slot="collapsible" {...props} />
}

function CollapsibleTrigger({ children, className, ...props }: CollapsiblePrimitive.Trigger.Props): React.ReactElement {
    return (
        <CollapsiblePrimitive.Trigger
            data-slot="collapsible-trigger"
            className={cn(
                `w-full group/collapsible-trigger flex items-center gap-2 text-xs/relaxed **:data-[slot=collapsible-trigger-icon]:size-4 **:data-[slot=collapsible-trigger-icon]:text-muted-foreground justify-start`,
                className
            )}
            render={<Button size="sm" className="px-2" />}
            {...props}
        >
            {children}
            <ChevronDownIcon
                data-slot="collapsible-trigger-icon"
                className="pointer-events-none shrink-0 group-data-[panel-open]/collapsible-trigger:hidden"
            />
            <ChevronUpIcon
                data-slot="collapsible-trigger-icon"
                className="pointer-events-none hidden shrink-0 group-data-[panel-open]/collapsible-trigger:inline"
            />
        </CollapsiblePrimitive.Trigger>
    )
}

function CollapsibleContent({ children, className, ...props }: CollapsiblePrimitive.Panel.Props): React.ReactElement {
    return (
        <CollapsiblePrimitive.Panel
            data-slot="collapsible-content"
            className="h-[var(--collapsible-panel-height)] overflow-hidden transition-[height] duration-200 ease-out data-[starting-style]:h-0 data-[ending-style]:h-0 relative z-1"
            {...props}
        >
            <div
                className={cn(
                    'px-2 pt-0 pb-4 [&_a]:underline [&_a]:underline-offset-3 [&_a]:hover:text-foreground [&_p:not(:last-child)]:mb-4',
                    className
                )}
            >
                {children}
            </div>
        </CollapsiblePrimitive.Panel>
    )
}

export { Collapsible, CollapsibleTrigger, CollapsibleContent }
