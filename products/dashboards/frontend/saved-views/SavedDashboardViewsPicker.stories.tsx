import type { Meta, StoryObj } from '@storybook/react'

import type { DashboardListSavedView } from './dashboardSavedViewsLogic'
import { SavedDashboardViewsPicker } from './SavedDashboardViewsPicker'

const privateViewNames = [
    'Activation dashboard',
    'Customer feedback',
    'Daily product review',
    'Error investigation',
    'Experiment results',
    'Feature adoption',
    'Funnel review',
    'Launch checklist',
    'Mobile metrics',
    'New user journeys',
    'Onboarding review',
    'Product dashboards',
]

const teamViewNames = [
    'Performance checks',
    'Pinned dashboards',
    'Product metrics',
    'Retention review',
    'Revenue dashboards',
    'Session replay review',
    'Support follow-up',
    'Team metrics',
    'Team planning',
    'Weekly review',
    'Workspace health',
    'Yearly planning',
]

const savedViews: DashboardListSavedView[] = [...privateViewNames, ...teamViewNames].map((name, index) => {
    const isPrivate = index < privateViewNames.length

    return {
        id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
        name,
        scope: isPrivate ? 'private' : 'team',
        filters: {
            search: index % 3 === 0 ? 'review' : '',
            createdBy: 'All users',
            pinned: index % 4 === 0,
            shared: index % 5 === 0,
            tags: index % 2 === 0 ? ['product'] : [],
            folder: index % 3 === 0 ? 'Product' : null,
        },
        created_at: '2026-08-20T15:30:00Z',
        updated_at: '2026-08-25T10:15:00Z',
        created_by: isPrivate ? 1 : 2,
        can_change_scope: isPrivate,
    }
})

const meta: Meta<typeof SavedDashboardViewsPicker> = {
    title: 'Products/Dashboards/Saved views/Picker',
    component: SavedDashboardViewsPicker,
    parameters: {
        layout: 'padded',
        testOptions: { snapshotTargetSelector: '.Popover' },
    },
    decorators: [
        (Story) => (
            <div className="absolute left-4 top-4">
                <Story />
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof SavedDashboardViewsPicker>

export const Default: Story = {
    args: {
        activeSavedView: undefined,
        activeSavedViewHasUnsavedChanges: false,
        isFiltering: true,
        savedViews,
        nextCursors: { private: null, team: null },
        loadingMore: false,
        updatingSavedView: false,
        loading: false,
        loadError: false,
        loadMoreFailed: false,
        canEdit: true,
        defaultOpen: true,
        onSaveAsNewView: () => undefined,
        onSaveChanges: () => undefined,
        onSelectView: () => undefined,
        onManageViews: () => undefined,
        onLoadMore: () => undefined,
        onRetryLoad: () => undefined,
    },
}

export const Loading: Story = {
    args: {
        ...Default.args,
        activeSavedView: undefined,
        savedViews: [],
        loading: true,
        defaultOpen: true,
    },
    parameters: {
        testOptions: {
            snapshotTargetSelector: '.Popover',
            waitForLoadersToDisappear: false,
        },
    },
}

export const MoreResults: Story = {
    args: {
        ...Default.args,
        nextCursors: { private: 'next-private-page', team: null },
    },
}

export const UnsavedChanges: Story = {
    args: {
        activeSavedView: savedViews[0],
        activeSavedViewHasUnsavedChanges: true,
        isFiltering: true,
        savedViews,
        nextCursors: { private: null, team: null },
        loadingMore: false,
        updatingSavedView: false,
        loading: false,
        loadError: false,
        loadMoreFailed: false,
        canEdit: true,
        defaultOpen: true,
        onSaveAsNewView: () => undefined,
        onSaveChanges: () => undefined,
        onSelectView: () => undefined,
        onManageViews: () => undefined,
        onLoadMore: () => undefined,
        onRetryLoad: () => undefined,
    },
}

export const ReadOnly: Story = {
    args: {
        activeSavedView: savedViews[0],
        activeSavedViewHasUnsavedChanges: true,
        isFiltering: true,
        savedViews,
        nextCursors: { private: null, team: null },
        loadingMore: false,
        updatingSavedView: false,
        loading: false,
        loadError: false,
        loadMoreFailed: false,
        canEdit: false,
        defaultOpen: true,
        onSaveAsNewView: () => undefined,
        onSaveChanges: () => undefined,
        onSelectView: () => undefined,
        onManageViews: () => undefined,
        onLoadMore: () => undefined,
        onRetryLoad: () => undefined,
    },
}
