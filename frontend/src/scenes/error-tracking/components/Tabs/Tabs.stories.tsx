import { IconLogomark } from '@posthog/icons'
import { Meta } from '@storybook/react'

import { Tabs } from '.'

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
        <Tabs.Root className="w-[800px]" defaultValue="stacktrace">
            <Tabs.Header>
                <IconLogomark className="text-xl" />
                <Tabs.List>
                    <Tabs.Trigger value="stacktrace" />
                    <Tabs.Trigger value="properties" />
                    <Tabs.Trigger value="session" />
                </Tabs.List>
                <div>2 seconds ago</div>
            </Tabs.Header>
            <Tabs.Content value="stacktrace">
                <Tabs.SubHeader>Tab sub header</Tabs.SubHeader>
                Stacktrace
            </Tabs.Content>
            <Tabs.Content value="properties">Properties</Tabs.Content>
            <Tabs.Content value="session">Session</Tabs.Content>
        </Tabs.Root>
    )
}
