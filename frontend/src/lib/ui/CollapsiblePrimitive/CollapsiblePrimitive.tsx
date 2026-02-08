import './CollapsiblePrimitive.scss'

import * as Collapsible from '@radix-ui/react-collapsible'

import { cn } from 'lib/utils/css-classes'

export interface CollapsiblePrimitiveProps extends Collapsible.CollapsibleProps {}
export function CollapsiblePrimitive({ ...props }: CollapsiblePrimitiveProps): JSX.Element {
    return <Collapsible.Root {...props} />
}

export interface CollapsiblePrimitiveContentProps extends Collapsible.CollapsibleContentProps {}
export function CollapsiblePrimitiveContent({ className, ...props }: CollapsiblePrimitiveContentProps): JSX.Element {
    return <Collapsible.Content className={cn('primitive-collapsible-content', className)} {...props} />
}

export interface CollapsiblePrimitiveTriggerProps extends Collapsible.CollapsibleTriggerProps {}
export function CollapsiblePrimitiveTrigger({ ...props }: CollapsiblePrimitiveTriggerProps): JSX.Element {
    return <Collapsible.Trigger {...props} />
}
