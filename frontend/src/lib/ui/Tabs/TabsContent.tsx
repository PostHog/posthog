import * as Tabs from '@radix-ui/react-tabs'

export interface TabsContentProps extends Tabs.TabsContentProps {}

export function TabsContent({ className, ...props }: TabsContentProps): JSX.Element {
    return <Tabs.Content {...props} />
}
