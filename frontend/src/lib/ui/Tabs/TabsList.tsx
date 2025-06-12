import * as Tabs from '@radix-ui/react-tabs'

export interface TabsListProps extends Tabs.TabsListProps {}

export function TabsList({ ...props }: TabsListProps): JSX.Element {
    return <Tabs.List {...props} />
}
