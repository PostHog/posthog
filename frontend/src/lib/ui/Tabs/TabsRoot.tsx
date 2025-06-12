import * as Tabs from '@radix-ui/react-tabs'

export interface TabsRootProps extends Tabs.TabsProps {}

export function TabsRoot({ ...props }: TabsRootProps): JSX.Element {
    return <Tabs.Root {...props} />
}
