import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { router } from 'kea-router'

import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { DashboardFilterBar } from 'scenes/dashboard/DashboardFilters'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { encodeURLFilters, SEARCH_PARAM_FILTERS_KEY } from 'scenes/dashboard/dashboardUtils'

import { mswDecorator } from '~/mocks/browser'
import { variableDataLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableDataLogic'
import { NodeKind } from '~/queries/schema/schema-general'
import { AccessControlLevel, DashboardMode, DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

type FilterBarState =
    | 'saved'
    | 'unsaved'
    | 'url-overrides'
    | 'layout'
    | 'narrow'
    | 'large'
    | 'previewing'
    | 'sql-overrides'

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

const SQL_VARIABLE_IDS = ['organization', 'region', 'plan']

const sqlVariablesDashboard: DashboardType<QueryBasedInsightModel> = {
    ...dashboard,
    tiles: [
        {
            id: 1,
            layouts: {},
            color: null,
            insight: {
                id: 1,
                short_id: 'sql-variables',
                name: 'SQL variable preview',
                query: {
                    kind: NodeKind.DataVisualizationNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query: 'select {variables.organization}, {variables.region}, {variables.plan}',
                        variables: Object.fromEntries(
                            SQL_VARIABLE_IDS.map((variableId) => [variableId, { variableId, code_name: variableId }])
                        ),
                    },
                    chartSettings: {},
                    tableSettings: {},
                },
            } as unknown as QueryBasedInsightModel,
        },
    ],
    persisted_variables: Object.fromEntries(
        [
            ['organization', 'example.com'],
            ['region', 'North America'],
            ['plan', 'enterprise'],
        ].map(([variableId, value]) => [variableId, { variableId, code_name: variableId, value, isNull: false }])
    ),
}

function DashboardFilterBarStory({ state }: { state: FilterBarState }): JSX.Element {
    let storyDashboard = dashboard
    if (state === 'large' || state === 'previewing') {
        storyDashboard = largeDashboard
    }
    if (state === 'sql-overrides') {
        storyDashboard = sqlVariablesDashboard
    }
    if (state === 'url-overrides') {
        const filters = encodeURLFilters({ date_from: '-7d' })
        router.actions.push(
            `/dashboard/${DASHBOARD_ID}?${SEARCH_PARAM_FILTERS_KEY}=${filters[SEARCH_PARAM_FILTERS_KEY]}`
        )
    } else {
        router.actions.push(`/dashboard/${DASHBOARD_ID}`)
    }
    const logic = dashboardLogic({ id: DASHBOARD_ID, dashboard: storyDashboard })
    logic.mount()

    if (state === 'sql-overrides') {
        variableDataLogic.mount()
        variableDataLogic.actions.loadVariablesSuccess(
            SQL_VARIABLE_IDS.map((variableId) => ({
                id: variableId,
                name: `QA ${variableId}`,
                code_name: variableId,
                type: 'String',
                default_value: '',
            }))
        )
    }

    if (state === 'unsaved' || state === 'narrow' || state === 'large' || state === 'previewing') {
        logic.actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
        logic.actions.setDates('-7d', null)
    }

    if (state === 'previewing') {
        logic.actions.previewDashboardChanges()
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

export const UrlOverridesAsUnsavedChanges: Story = {
    args: { state: 'url-overrides' },
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

export const LargeDashboardPreviewingFilters: Story = {
    args: { state: 'previewing' },
}

export const SqlVariablesBeforeAdvancedOptions: Story = {
    args: { state: 'sql-overrides' },
}
