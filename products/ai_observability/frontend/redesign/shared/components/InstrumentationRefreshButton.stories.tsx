import type { Meta, StoryObj } from '@storybook/react'

import { InstrumentationRefreshButton } from './InstrumentationRefreshButton'

const meta: Meta<typeof InstrumentationRefreshButton> = {
    title: 'Scenes-App/AI observability/Shared/Instrumentation refresh button',
    component: InstrumentationRefreshButton,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        refreshing: false,
        refreshFailed: false,
        pendingCheckKey: null,
        onRefresh: () => {},
        size: 'small',
        'data-attr': 'instrumentation-refresh-story',
    },
}
export default meta

type Story = StoryObj<typeof InstrumentationRefreshButton>

export const Idle: Story = {}

export const AfterAFailedRefresh: Story = { args: { refreshFailed: true } }

export const HeldWhileACheckSaves: Story = { args: { pendingCheckKey: 'sessions' } }
