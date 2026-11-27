import { Meta, StoryObj } from '@storybook/react'

import { IconTodayAnalytics } from './IconTodayAnalytics'
import { IconTodayAutomate } from './IconTodayAutomate'
import { IconTodayChats } from './IconTodayChats'
import { IconTodayData } from './IconTodayData'
import { IconTodayHome } from './IconTodayHome'
import { IconTodayMonitor } from './IconTodayMonitor'
import { IconTodayPeople } from './IconTodayPeople'
import { IconTodayProducts } from './IconTodayProducts'
import { IconTodayRelease } from './IconTodayRelease'

const ICONS = {
    home: IconTodayHome,
    chats: IconTodayChats,
    analytics: IconTodayAnalytics,
    monitor: IconTodayMonitor,
    people: IconTodayPeople,
    release: IconTodayRelease,
    automate: IconTodayAutomate,
    data: IconTodayData,
    products: IconTodayProducts,
}

function IconRow({ active }: { active: boolean }): JSX.Element {
    return (
        <div className="flex gap-4 text-muted-foreground [&_svg]:size-5">
            {Object.entries(ICONS).map(([name, Icon]) => (
                <span
                    key={name}
                    data-today-rail-hover
                    data-today-rail-active={active || undefined}
                    className="flex size-10 items-center justify-center rounded-md"
                >
                    <Icon />
                </span>
            ))}
        </div>
    )
}

const meta: Meta = {
    title: 'Layout/Today/Rail icons',
    parameters: {
        layout: 'padded',
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

export const OutlineAndFilled: StoryObj = {
    render: () => (
        <div className="flex flex-col gap-2">
            <IconRow active={false} />
            <IconRow active />
        </div>
    ),
}
