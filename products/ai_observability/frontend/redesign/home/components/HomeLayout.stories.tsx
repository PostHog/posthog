import type { Meta, StoryObj } from '@storybook/react'

import { LemonBanner } from '@posthog/lemon-ui'

import { METRICS, METRICS_NOT_SET_UP, RANGE_TOO_LONG_DETAIL, TILE_LINKS } from '../homeFixtures'
import { HomeLayout } from './HomeLayout'
import { HomeRangeTooLong } from './HomeRangeTooLong'
import { KpiTileRow } from './KpiTileRow'
import { OpenDashboardLink } from './OpenDashboardLink'

const meta: Meta<typeof HomeLayout> = {
    title: 'Scenes-App/AI observability/Home/Home layout',
    component: HomeLayout,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        filters: <span>Last 7 days</span>,
        dashboardLink: <OpenDashboardLink dashboardId={42} />,
        tiles: (
            <KpiTileRow
                metrics={METRICS}
                loading={false}
                links={TILE_LINKS}
                openChartKey={null}
                onToggleChart={() => {}}
            />
        ),
        showComparison: true,
        instrumentation: <LemonBanner type="info">Instrumentation slot</LemonBanner>,
    },
}
export default meta

type Story = StoryObj<typeof HomeLayout>

export const Wide: Story = {}

export const NarrowContainer: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="w-130">
                <StoryComponent />
            </div>
        ),
    ],
}

export const AllNotSetUp: Story = {
    args: {
        tiles: (
            <KpiTileRow
                metrics={METRICS_NOT_SET_UP}
                loading={false}
                links={TILE_LINKS}
                openChartKey={null}
                onToggleChart={() => {}}
            />
        ),
    },
}

export const Loading: Story = {
    args: {
        tiles: <KpiTileRow metrics={null} loading links={TILE_LINKS} openChartKey={null} onToggleChart={() => {}} />,
        showComparison: false,
    },
}

export const RangeTooLong: Story = {
    args: { tiles: <HomeRangeTooLong detail={RANGE_TOO_LONG_DETAIL} />, showComparison: false },
}
