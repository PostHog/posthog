import * as Tabs from '@radix-ui/react-tabs'
import { cn } from 'lib/utils/css-classes'

export interface TabsContentProps extends Tabs.TabsContentProps {}

export function TabsContent({ className, ...props }: TabsContentProps): JSX.Element {
    return <Tabs.Content className={cn('tabs-content', className)} {...props} />
}
