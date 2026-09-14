import type { Meta, StoryObj } from '@storybook/react'

import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import type { DashboardListSavedView } from './dashboardSavedViewsLogic'
import { ManageDashboardSavedViews } from './ManageDashboardSavedViews'

const viewNames = [
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
    'Performance checks',
    'Pinned dashboards',
    'Product metrics',
    'Retention review',
    'Revenue dashboards',
    'Session replay review',
    'Support follow-up',
    'Team planning',
    'Weekly review',
]

const filters: DashboardListSavedView['filters'][] = [
    { search: '', createdBy: 'All users', pinned: false, shared: true, tags: ['product'], folder: null },
    { search: 'feedback', createdBy: [2], pinned: false, shared: false, tags: [], folder: null },
    { search: '', createdBy: 'All users', pinned: true, shared: false, tags: [], folder: 'Product' },
    { search: 'error', createdBy: [3], pinned: false, shared: false, tags: ['engineering'], folder: null },
    { search: '', createdBy: 'All users', pinned: false, shared: false, tags: ['experiments'], folder: 'Growth' },
    { search: 'adoption', createdBy: [4], pinned: false, shared: true, tags: [], folder: null },
    { search: '', createdBy: 'All users', pinned: false, shared: false, tags: ['product', 'growth'], folder: null },
    { search: 'launch', createdBy: [5], pinned: true, shared: false, tags: [], folder: 'Product' },
]

const creators: Record<number, { first_name: string; last_name: string; email: string }> = {
    1: { first_name: 'You', last_name: '', email: 'you@example.com' },
    2: { first_name: 'Alex', last_name: 'Chen', email: 'alex@example.com' },
    3: { first_name: 'Blair', last_name: 'Kim', email: 'blair@example.com' },
    4: { first_name: 'Casey', last_name: 'Morgan', email: 'casey@example.com' },
    5: { first_name: 'Devon', last_name: 'Reed', email: 'devon@example.com' },
}

const creatorName = (id: number): string => {
    const creator = creators[id]
    return creator ? `${creator.first_name} ${creator.last_name}`.trim() : 'Unknown user'
}

const savedViews: DashboardListSavedView[] = viewNames.map((name, index) => {
    const isPrivate = index < 8
    const createdBy = isPrivate ? 1 : (index % 4) + 2

    return {
        id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
        name,
        scope: isPrivate ? 'private' : 'team',
        filters: filters[index % filters.length],
        created_at: `2026-08-${String(1 + index).padStart(2, '0')}T10:00:00Z`,
        updated_at: `2026-08-${String(1 + index).padStart(2, '0')}T12:00:00Z`,
        created_by: createdBy,
        can_change_scope: isPrivate || createdBy === 1,
    }
})

const meta: Meta<typeof ManageDashboardSavedViews> = {
    title: 'Products/Dashboards/Saved views/Manage',
    component: ManageDashboardSavedViews,
    parameters: {
        layout: 'padded',
        mockDate: '2026-08-26T12:00:00Z',
    },
    decorators: [
        (Story) => (
            <div className="max-w-7xl">
                <Story />
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof ManageDashboardSavedViews>

export const Default: Story = {
    args: {
        views: savedViews,
        nextCursors: { private: null, team: null },
        editDisabledReason: null,
        onUpdate: async (view, update) => ({ ...view, ...update }),
        onDelete: async () => undefined,
        onLoadMore: async () => null,
        renderCreator: (view) => {
            const id = view.created_by ?? 0
            const creator = creators[id]
            const name = creatorName(id)

            return (
                <span className="flex items-center gap-2">
                    <ProfilePicture user={creator} name={name} size="md" />
                    <span>{name}</span>
                </span>
            )
        },
        renderFilters: (filters) => {
            const labels: string[] = []
            if (filters.shared) {
                labels.push('Shared')
            }
            if (filters.pinned) {
                labels.push('Pinned')
            }
            if (filters.tags?.length) {
                labels.push(`Tags: ${filters.tags.join(', ')}`)
            }
            if (filters.createdBy !== 'All users') {
                labels.push(`Created by: ${filters.createdBy.map(creatorName).join(', ')}`)
            }
            if (filters.folder != null) {
                labels.push(`Folder: ${filters.folder || 'Project root'}`)
            }
            if (filters.search) {
                labels.push(`Search: “${filters.search}”`)
            }
            return labels.join(', ') || 'No filters'
        },
    },
}
