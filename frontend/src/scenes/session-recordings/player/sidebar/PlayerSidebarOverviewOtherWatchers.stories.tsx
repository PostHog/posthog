import { Meta } from '@storybook/react'

import { PlayerSidebarOverviewOtherWatchers } from './PlayerSidebarOverviewOtherWatchers'

const meta: Meta<typeof PlayerSidebarOverviewOtherWatchers> = {
    title: 'Scenes/Session Recordings/Player/Sidebar/PlayerSidebarOverviewOtherWatchers',
    component: PlayerSidebarOverviewOtherWatchers,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    tags: ['autodocs'],
}
export default meta

export function Default(): JSX.Element {
    return <PlayerSidebarOverviewOtherWatchers />
}

export function Expanded(): JSX.Element {
    return <PlayerSidebarOverviewOtherWatchers startExpanded={true} />
}

export function WithMultipleViewers(): JSX.Element {
    return <PlayerSidebarOverviewOtherWatchers startExpanded={true} />
}

export function Loading(): JSX.Element {
    return <PlayerSidebarOverviewOtherWatchers />
}

export function NoOtherWatchers(): JSX.Element {
    return <PlayerSidebarOverviewOtherWatchers />
}
