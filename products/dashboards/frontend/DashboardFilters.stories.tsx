import type { Meta, StoryObj } from '@storybook/react'
import { screen } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'
import { router } from 'kea-router'

import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { DashboardFilterBar } from 'scenes/dashboard/DashboardFilters'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { encodeURLFilters, encodeURLVariables } from 'scenes/dashboard/dashboardUtils'

import { mswDecorator } from '~/mocks/browser'
import { variableDataLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableDataLogic'
import { NodeKind, type DashboardFilter } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    DashboardType,
    PropertyFilterType,
    PropertyOperator,
    QueryBasedInsightModel,
} from '~/types'

type FilterBarState = 'saved' | 'unsaved'
type DashboardFilterKind = 'date' | 'properties' | 'breakdown' | 'interval' | 'testAccounts'
type DashboardChangeKind = DashboardFilterKind | 'sqlVariables'

const dashboardFilterKinds: DashboardFilterKind[] = ['date', 'properties', 'breakdown', 'interval', 'testAccounts']
const dashboardChangeKinds: DashboardChangeKind[] = [...dashboardFilterKinds, 'sqlVariables']
const dashboardChangeKindLabels: Record<DashboardChangeKind, string> = {
    date: 'Date',
    properties: 'Properties',
    breakdown: 'Breakdown',
    interval: 'Interval',
    testAccounts: 'Test accounts',
    sqlVariables: 'SQL variables',
}

interface DashboardFilterBarStoryProps {
    state: FilterBarState
    readOnly: boolean
    filterChanges: DashboardChangeKind[]
    urlOverrideFilters: DashboardChangeKind[]
    narrow: boolean
}

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

const SQL_VARIABLE_ID = 'organization'
const SQL_VARIABLE_DEFAULT = 'Default organization'
const SQL_VARIABLE_OVERRIDE = 'Example organization'

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
                        query: 'select {variables.organization}',
                        variables: { [SQL_VARIABLE_ID]: { variableId: SQL_VARIABLE_ID, code_name: SQL_VARIABLE_ID } },
                    },
                    chartSettings: {},
                    tableSettings: {},
                },
            } as unknown as QueryBasedInsightModel,
        },
    ],
    persisted_variables: {
        [SQL_VARIABLE_ID]: {
            code_name: SQL_VARIABLE_ID,
            variableId: SQL_VARIABLE_ID,
            value: SQL_VARIABLE_DEFAULT,
            isNull: false,
        },
    },
}

function dashboardFilters(filterKinds: DashboardChangeKind[]): DashboardFilter {
    return {
        ...(filterKinds.includes('date') ? { date_from: '-7d' } : {}),
        ...(filterKinds.includes('properties')
            ? {
                  properties: [
                      {
                          key: 'browser',
                          type: PropertyFilterType.Event,
                          operator: PropertyOperator.Exact,
                          value: 'Chrome',
                      },
                  ],
              }
            : {}),
        ...(filterKinds.includes('breakdown')
            ? { breakdown_filter: { breakdown: '$browser', breakdown_type: 'event' } }
            : {}),
        ...(filterKinds.includes('interval') ? { interval: 'week' } : {}),
        ...(filterKinds.includes('testAccounts') ? { filterTestAccounts: true } : {}),
    }
}

function applyUnsavedFilters(logic: ReturnType<typeof dashboardLogic.build>, filterKinds: DashboardChangeKind[]): void {
    const filters = dashboardFilters(filterKinds)

    logic.actions.setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
    if (filters.date_from) {
        logic.actions.setDates(filters.date_from, null)
    }
    if (filters.properties) {
        logic.actions.setProperties(filters.properties)
    }
    if (filters.breakdown_filter) {
        logic.actions.setBreakdownFilter(filters.breakdown_filter)
    }
    if (filters.interval) {
        logic.actions.setInterval(filters.interval)
    }
    if (filters.filterTestAccounts) {
        logic.actions.setFilterTestAccounts(filters.filterTestAccounts)
    }
    if (filterKinds.includes('sqlVariables')) {
        logic.actions.overrideVariableValue(SQL_VARIABLE_ID, SQL_VARIABLE_OVERRIDE, false)
    }
}

function DashboardFilterBarStory({
    state,
    readOnly,
    filterChanges,
    urlOverrideFilters,
    narrow,
}: DashboardFilterBarStoryProps): JSX.Element {
    const hasSqlVariables =
        (state !== 'saved' && filterChanges.includes('sqlVariables')) || urlOverrideFilters.includes('sqlVariables')
    const storyDashboard = {
        ...(hasSqlVariables ? sqlVariablesDashboard : dashboard),
        user_access_level: readOnly ? AccessControlLevel.Viewer : AccessControlLevel.Editor,
    }

    router.actions.push(`/dashboard/${DASHBOARD_ID}`, {
        ...encodeURLFilters(dashboardFilters(urlOverrideFilters)),
        ...encodeURLVariables(
            urlOverrideFilters.includes('sqlVariables') ? { organization: SQL_VARIABLE_OVERRIDE } : {}
        ),
    })

    const logic = dashboardLogic({ id: DASHBOARD_ID, dashboard: storyDashboard })
    logic.mount()

    if (hasSqlVariables) {
        variableDataLogic.mount()
        variableDataLogic.actions.loadVariablesSuccess([
            {
                id: SQL_VARIABLE_ID,
                name: 'Organization',
                code_name: SQL_VARIABLE_ID,
                type: 'String',
                default_value: SQL_VARIABLE_DEFAULT,
            },
        ])
    }

    if (state !== 'saved') {
        logic.actions.setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
    }

    if (state !== 'saved') {
        applyUnsavedFilters(logic, filterChanges)
    }

    return (
        <div className={`p-4 ${narrow ? 'w-96' : 'max-w-5xl'}`}>
            <BindLogic logic={dashboardLogic} props={{ id: DASHBOARD_ID, dashboard: storyDashboard }}>
                <DashboardFilterBar />
            </BindLogic>
        </div>
    )
}

const meta: Meta<DashboardFilterBarStoryProps> = {
    component: DashboardFilterBarStory,
    title: 'Products/Dashboards/Filter bar',
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/events/values': { results: [] },
                '/api/environments/:team_id/persons/properties': [],
                '/api/environments/:team_id/insight_variables/': {
                    results: [
                        {
                            id: SQL_VARIABLE_ID,
                            name: 'Organization',
                            code_name: SQL_VARIABLE_ID,
                            type: 'String',
                            default_value: SQL_VARIABLE_DEFAULT,
                        },
                    ],
                },
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
    argTypes: {
        state: { control: 'inline-radio', options: ['saved', 'unsaved'] satisfies FilterBarState[] },
        readOnly: { control: 'boolean' },
        filterChanges: {
            control: { type: 'check', labels: dashboardChangeKindLabels },
            options: dashboardChangeKinds,
            name: 'Unsaved filter changes',
        },
        urlOverrideFilters: {
            control: { type: 'check', labels: dashboardChangeKindLabels },
            options: dashboardChangeKinds,
            name: 'URL override filters',
        },
        narrow: { control: 'boolean' },
    },
    args: {
        state: 'unsaved',
        readOnly: false,
        filterChanges: dashboardChangeKinds,
        urlOverrideFilters: [],
        narrow: false,
    },
}

export default meta

type Story = StoryObj<DashboardFilterBarStoryProps>

export const FilterBar: Story = {}

export const UnsavedChangesPopover: Story = {
    args: {
        state: 'unsaved',
        filterChanges: dashboardFilterKinds,
    },
    play: async () => {
        await userEvent.click(await screen.findByLabelText('Show 5 unsaved filters'))
        await screen.findByText('Unsaved changes')
    },
}
