import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { router } from 'kea-router'

import { DashboardEventSource } from 'lib/utils/eventUsageLogic'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, DashboardMode, DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

import { DashboardFilterBar } from './DashboardFilters'
import { dashboardLogic } from './dashboardLogic'
import { encodeURLFilters, SEARCH_PARAM_FILTERS_KEY } from './dashboardUtils'

type FilterBarState = 'saved' | 'unsaved' | 'temporary' | 'temporary-viewer' | 'layout' | 'narrow' | 'large'

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
    if (state === 'large') {
        storyDashboard = largeDashboard
    }
    if (state === 'temporary-viewer') {
        storyDashboard = { ...dashboard, user_access_level: AccessControlLevel.Viewer }
    }
    const logic = dashboardLogic({ id: DASHBOARD_ID, dashboard: storyDashboard })
    logic.mount()

    if (state === 'temporary' || state === 'temporary-viewer') {
        const filters = encodeURLFilters({ date_from: '-7d' })
        router.actions.push(
            `/dashboard/${DASHBOARD_ID}?${SEARCH_PARAM_FILTERS_KEY}=${filters[SEARCH_PARAM_FILTERS_KEY]}`
        )
    } else {
        router.actions.push(`/dashboard/${DASHBOARD_ID}`)
    }

    if (state === 'unsaved' || state === 'narrow' || state === 'large') {
        logic.actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
        logic.actions.setDates('-7d', null)
    }

    if (state === 'layout') {
        logic.actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.SceneCommonButtons)
        logic.actions.setDates('-7d', null)
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
    title: 'Scenes/Dashboards/Filter bar',
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

export const TemporaryFilters: Story = {
    args: { state: 'temporary' },
}

export const TemporaryFiltersWithoutEditAccess: Story = {
    args: { state: 'temporary-viewer' },
}

export const LayoutEditingWithUnsavedFilters: Story = {
    args: { state: 'layout' },
}

export const NarrowUnsavedFilters: Story = {
    args: { state: 'narrow' },
}

export const LargeDashboardUnsavedFilters: Story = {
    args: { state: 'large' },
}
