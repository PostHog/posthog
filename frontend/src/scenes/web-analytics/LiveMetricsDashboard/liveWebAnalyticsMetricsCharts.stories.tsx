import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { BotEventsPerMinuteChart, UsersPerMinuteChart } from './liveWebAnalyticsMetricsCharts'
import { ChartDataPoint } from './LiveWebAnalyticsMetricsTypes'

// Fixed base so the HH:mm axis/tooltip labels — and therefore the snapshots — stay deterministic.
const BASE_TS = dayjs('2024-08-13T08:00:00Z').valueOf()
const TIMEZONE = 'UTC'

const NEW = [4, 6, 3, 8, 5, 9, 7, 11, 6, 10, 8, 12, 9, 14, 10, 13, 11, 15, 12, 9, 7, 10, 8, 6, 9, 11, 7, 5, 8, 6]
const RETURNING = [2, 3, 5, 4, 6, 3, 7, 5, 8, 6, 9, 7, 5, 8, 6, 9, 7, 10, 8, 11, 9, 6, 8, 5, 7, 9, 6, 4, 7, 5]
const BOTS = [0, 1, 0, 3, 0, 2, 5, 1, 0, 4, 2, 0, 7, 3, 1, 0, 2, 6, 0, 3, 1, 0, 4, 2, 0, 5, 1, 0, 3, 2]

const DATA: ChartDataPoint[] = NEW.map((newUsers, i) => {
    const timestamp = BASE_TS + i * 60_000
    const returningUsers = RETURNING[i]
    return {
        minute: dayjs(timestamp).format('HH:mm'),
        timestamp,
        newUsers,
        returningUsers,
        users: newUsers + returningUsers,
        pageviews: (newUsers + returningUsers) * 3,
        botEvents: BOTS[i],
    }
})

const EMPTY: ChartDataPoint[] = DATA.map((d) => ({
    ...d,
    newUsers: 0,
    returningUsers: 0,
    users: 0,
    pageviews: 0,
    botEvents: 0,
}))

const Sized = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <div className="h-80 w-[36rem]">{children}</div>
)

type Story = StoryObj<typeof UsersPerMinuteChart>
const meta: Meta<typeof UsersPerMinuteChart> = {
    title: 'Scenes-App/Web Analytics/LiveMetricsCharts',
    component: UsersPerMinuteChart,
}
export default meta

export const UsersPerMinute: Story = {
    render: () => (
        <Sized>
            <UsersPerMinuteChart data={DATA} timezone={TIMEZONE} />
        </Sized>
    ),
}

export const UsersPerMinuteEmpty: Story = {
    render: () => (
        <Sized>
            <UsersPerMinuteChart data={EMPTY} timezone={TIMEZONE} />
        </Sized>
    ),
}

export const BotEventsPerMinute: Story = {
    render: () => (
        <Sized>
            <BotEventsPerMinuteChart data={DATA} timezone={TIMEZONE} />
        </Sized>
    ),
}

export const BotEventsPerMinuteEmpty: Story = {
    render: () => (
        <Sized>
            <BotEventsPerMinuteChart data={EMPTY} timezone={TIMEZONE} />
        </Sized>
    ),
}
