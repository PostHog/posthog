import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { DashboardFilterBar } from 'scenes/dashboard/DashboardFilters'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, DashboardMode, DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

type FilterBarState = 'saved' | 'unsaved' | 'narrow' | 'large' | 'previewing'

const DASHBOARD_ID = 955

const dashboard: DashboardType<QueryBasedInsightModel> = {
    id: DASHBOARD_ID,
    name: 'Dashboard filter states',
    description: '',
    pinned: false,
    tiles: [],
    tags: [],
    created_at: '2020-01-01T00:00:00Z',
    created_by: null,
    last_accessed_at: '2020-01-01T00:00:00Z',
    is_shared: false,
    deleted: false,
    creation_mode: 'default',
    user_access_level: AccessControlLevel.Editor,
    filters: {},
    variables: {},
}

const largeDashboard: DashboardType<QueryBasedInsightModel> = {
    ...dashboard,
    tiles: Array.from(
        { length: 51 },
        (_, id) =>
            ({
                id,
                layouts: {},
                insight: {},
            }) as DashboardTile<QueryBasedInsightModel>
    ),
}

function DashboardFilterBarStory({ state }: { state: FilterBarState }): JSX.Element {
    let storyDashboard = dashboard
    if (state === 'large' || state === 'previewing') {
        storyDashboard = largeDashboard
    }
    const logic = dashboardLogic({ id: DASHBOARD_ID, dashboard: storyDashboard })
    logic.mount()

    if (state === 'unsaved' || state === 'narrow' || state === 'large' || state === 'previewing') {
        logic.actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
        logic.actions.setDates('-7d', null)
    }

    if (state === 'previewing') {
        logic.actions.previewDashboardChanges()
    }

    return (
        <div className={`p-4 ${state === 'narrow' ? 'w-96' : 'max-w-5xl'}`}>
            <BindLogic logic={dashboardLogic} props={{ id: DASHBOARD_ID, dashboard: storyDashboard }}>
                <DashboardFilterBar />
            </BindLogic>
        </div>
    )
}

const meta: Meta<typeof DashboardFilterBarStory> = {
    component: DashboardFilterBarStory,
    title: 'Products/Dashboards/Filter bar',
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/events/values': { results: [] },
                '/api/environments/:team_id/persons/properties': [],
            },
            post: {
                '/api/environments/:team_id/query/': () => [200, { results: [] }],
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}

export default meta

type Story = StoryObj<typeof DashboardFilterBarStory>

export const SavedFilters: Story = {
    args: { state: 'saved' },
}

export const UnsavedFilters: Story = {
    args: { state: 'unsaved' },
}

export const NarrowUnsavedFilters: Story = {
    args: { state: 'narrow' },
}

export const LargeDashboardUnsavedFilters: Story = {
    args: { state: 'large' },
}

export const LargeDashboardPreviewingFilters: Story = {
    args: { state: 'previewing' },
}
