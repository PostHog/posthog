import { IconLogomark } from '@posthog/icons'
import { Meta } from '@storybook/react'

import { TabsContent } from './TabsContent'
import { TabsHeader } from './TabsHeader'
import { TabsList } from './TabsList'
import { TabsRoot } from './TabsRoot'
import { TabsSubHeader } from './TabsSubHeader'
import { TabsTrigger } from './TabsTrigger'

const meta: Meta = {
    title: 'ErrorTracking/Tabs',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
}

export default meta

export function TabsSimple(): JSX.Element {
    return (
        <TabsRoot className="w-[800px]" defaultValue="stacktrace">
            <TabsHeader>
                <IconLogomark className="text-xl" />
                <TabsList>
                    <TabsTrigger value="stacktrace" />
                    <TabsTrigger value="properties" />
                    <TabsTrigger value="session" />
                </TabsList>
                <div>2 seconds ago</div>
            </TabsHeader>
            <TabsContent value="stacktrace">
                <TabsSubHeader>Tab sub header</TabsSubHeader>
                Stacktrace
            </TabsContent>
            <TabsContent value="properties">Properties</TabsContent>
            <TabsContent value="session">Session</TabsContent>
        </TabsRoot>
    )
}
