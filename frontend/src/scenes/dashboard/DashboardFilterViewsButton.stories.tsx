import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { DashboardFilterView } from '~/types'

import { DashboardFilterViewsButton } from './DashboardFilterViewsButton'

const views: DashboardFilterView[] = [
    { id: 'enterprise', name: 'Enterprise', filters: { date_from: '-30d' } },
    { id: 'self-serve', name: 'Self-serve', filters: { date_from: '-7d' } },
    { id: 'europe', name: 'Europe', filters: { date_from: '-14d' } },
]

const meta: Meta<typeof DashboardFilterViewsButton> = {
    title: 'Scenes/Dashboard/Filter views',
    component: DashboardFilterViewsButton,
    args: {
        views,
        canEdit: true,
        defaultOpen: true,
        onCreate: () => {},
        onSelect: () => {},
        onDelete: () => {},
    },
    parameters: {
        featureFlags: [FEATURE_FLAGS.DASHBOARD_FILTER_SAVED_VIEWS],
    },
}

export default meta
type Story = StoryObj<typeof DashboardFilterViewsButton>

export const SavedViews: Story = {}

export const ActiveView: Story = {
    args: {
        activeView: views[0],
    },
}

export const Viewer: Story = {
    args: {
        canEdit: false,
    },
}

export const Empty: Story = {
    args: {
        views: [],
    },
}
