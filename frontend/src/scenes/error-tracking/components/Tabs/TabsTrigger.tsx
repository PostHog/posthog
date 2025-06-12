import * as Tabs from '@radix-ui/react-tabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

export interface TabsTriggerProps extends Tabs.TabsTriggerProps {}

export function TabsTrigger({ children, value, className, ...props }: TabsTriggerProps): JSX.Element {
    return (
        <Tabs.Trigger className={cn('tabs-trigger', className)} value={value} {...props}>
            {children ?? capitalizeFirstLetter(value)}
        </Tabs.Trigger>
    )
}
