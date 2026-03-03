import { Collapsible } from '@base-ui/react/collapsible'

import { cn } from 'lib/utils/css-classes'

export type CollapsiblePrimitiveProps = React.ComponentProps<typeof Collapsible.Root>
export function CollapsiblePrimitive(props: CollapsiblePrimitiveProps): JSX.Element {
    return <Collapsible.Root {...props} />
}

export type CollapsiblePrimitiveContentProps = React.ComponentProps<typeof Collapsible.Panel>
export function CollapsiblePrimitiveContent({ className, ...props }: CollapsiblePrimitiveContentProps): JSX.Element {
    return (
        <Collapsible.Panel
            className={cn(
                'h-[var(--collapsible-panel-height)] overflow-hidden transition-[height] duration-200 ease-out data-[starting-style]:h-0 data-[ending-style]:h-0',
                className
            )}
            {...props}
        />
    )
}

export type CollapsiblePrimitiveTriggerProps = React.ComponentProps<typeof Collapsible.Trigger>
export function CollapsiblePrimitiveTrigger(props: CollapsiblePrimitiveTriggerProps): JSX.Element {
    return <Collapsible.Trigger {...props} />
}
