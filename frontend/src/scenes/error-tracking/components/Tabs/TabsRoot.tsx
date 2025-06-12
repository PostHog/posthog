import * as Tabs from '@radix-ui/react-tabs'
import { cn } from 'lib/utils/css-classes'

export interface TabsRootProps extends Tabs.TabsProps {}

export function TabsRoot({ className, ...props }: TabsRootProps): JSX.Element {
    return <Tabs.Root className={cn('tabs-root', className)} {...props} />
}
