import './TabsPrimitive.scss'

import * as Tabs from '@radix-ui/react-tabs'
import { cn } from 'lib/utils/css-classes'

export interface TabsPrimitiveProps extends Tabs.TabsProps {}
export function TabsPrimitive({ ...props }: TabsPrimitiveProps): JSX.Element {
    return <Tabs.Root {...props} />
}

export interface TabsPrimitiveListProps extends Tabs.TabsListProps {}
export function TabsPrimitiveList({ ...props }: TabsPrimitiveListProps): JSX.Element {
    return <Tabs.List {...props} />
}

export interface TabsPrimitiveContentProps extends Tabs.TabsContentProps {}
export function TabsPrimitiveContent({ ...props }: TabsPrimitiveContentProps): JSX.Element {
    return <Tabs.Content {...props} />
}

export interface TabsPrimitiveTriggerProps extends Tabs.TabsTriggerProps {}

export function TabsPrimitiveTrigger({ className, ...props }: TabsPrimitiveTriggerProps): JSX.Element {
    return <Tabs.Trigger className={cn('tabs-trigger', className)} {...props} />
}
