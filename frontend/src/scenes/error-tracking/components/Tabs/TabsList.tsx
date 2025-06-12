import * as Tabs from '@radix-ui/react-tabs'

export interface TabsListProps extends Tabs.TabsListProps {}

export function TabsList({ className, ...props }: TabsListProps): JSX.Element {
    return <Tabs.List className={`tabs-list ${className}`} {...props} />
}
