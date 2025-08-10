import { IconLogomark } from '@posthog/icons'
import type { Meta } from '@storybook/react'

import { TabsPrimitive, TabsPrimitiveContent, TabsPrimitiveList, TabsPrimitiveTrigger } from './TabsPrimitive'

const meta: Meta = {
    title: 'UI/TabsPrimitive',
    tags: ['autodocs'],
}

export default meta

export function TabsSimple(): JSX.Element {
    return (
        <TabsPrimitive className="w-[800px]" defaultValue="stacktrace">
            <div className="flex justify-between items-center">
                <IconLogomark className="text-xl" />
                <TabsPrimitiveList>
                    <TabsPrimitiveTrigger className="px-2" value="stacktrace">
                        Stacktrace
                    </TabsPrimitiveTrigger>
                    <TabsPrimitiveTrigger className="px-2" value="properties">
                        Properties
                    </TabsPrimitiveTrigger>
                    <TabsPrimitiveTrigger className="px-2" value="session">
                        Session
                    </TabsPrimitiveTrigger>
                </TabsPrimitiveList>
                <div>2 seconds ago</div>
            </div>
            <TabsPrimitiveContent value="stacktrace">
                <div className="tabs-sub-header border-b-1 bg-surface-secondary px-2 py-1">Tab sub header</div>
                Stacktrace
            </TabsPrimitiveContent>
            <TabsPrimitiveContent value="properties">Properties</TabsPrimitiveContent>
            <TabsPrimitiveContent value="session">Session</TabsPrimitiveContent>
        </TabsPrimitive>
    )
}
