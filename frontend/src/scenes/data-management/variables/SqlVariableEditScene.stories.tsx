import { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import { FEATURE_FLAGS, STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { Variable } from '~/queries/nodes/DataVisualization/types'

import { expect, userEvent } from 'storybook/test'

const LIST_VARIABLE: Variable = {
    id: 'variable-plan',
    name: 'Plan',
    code_name: 'plan',
    type: 'List',
    values: ['free', 'starter', 'scale'],
    is_multi: true,
    default_value: ['free', 'scale'],
}

const DATE_VARIABLE: Variable = {
    id: 'variable-start',
    name: 'Start date',
    code_name: 'start_date',
    type: 'Date',
    default_value: '-7d',
}

const QUERY_VARIABLE: Variable = {
    id: 'variable-region',
    name: 'Region',
    code_name: 'region',
    type: 'List',
    values: [],
    values_query: 'select code, name from regions',
    values_query_connection_id: null,
    is_multi: false,
    default_value: 'eu',
}

const INSIGHT_USING_PLAN = {
    id: 1,
    short_id: 'abc123',
    name: 'Revenue by plan',
    description: 'Monthly revenue split by plan',
    created_at: '2023-01-10T10:00:00Z',
    last_modified_at: '2023-02-01T12:00:00Z',
    last_viewed_at: null,
    query: {
        kind: 'DataVisualizationNode',
        source: { kind: 'HogQLQuery', query: 'select 1', variables: { plan: { variableId: 'variable-plan' } } },
    },
}

const VARIABLES = [LIST_VARIABLE, DATE_VARIABLE, QUERY_VARIABLE]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management/SQL Variables/Edit',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-15',
        pageUrl: urls.variableEdit(LIST_VARIABLE.id),
        featureFlags: [...STORYBOOK_FEATURE_FLAGS, FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { waitForSelector: '[data-attr="variable-insights-table"]', snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/insight_variables/': toPaginatedResponse(VARIABLES),
                '/api/environments/:team_id/insight_variables/': toPaginatedResponse(VARIABLES),
                '/api/projects/:team_id/insights/': toPaginatedResponse([INSIGHT_USING_PLAN]),
                '/api/environments/:team_id/insights/': toPaginatedResponse([INSIGHT_USING_PLAN]),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const SqlVariableEditQuillList: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvas.getByText('Revenue by plan')).toBeInTheDocument())
        // The static options and the multi-select default both render as chips.
        await expect(canvas.getAllByText('starter').length).toBeGreaterThan(0)
        await expect(canvas.getByRole('switch', { name: 'Allow multiple selections' })).toBeChecked()

        const dragHandleOrder = (): string[] =>
            canvas.getAllByRole('button', { name: /^Drag .+ to reorder$/ }).map((el) => el.getAttribute('aria-label')!)
        await expect(dragHandleOrder()).toEqual([
            'Drag free to reorder',
            'Drag starter to reorder',
            'Drag scale to reorder',
        ])
        canvas.getByRole('button', { name: 'Drag free to reorder' }).focus()
        await userEvent.keyboard(' ')
        await userEvent.keyboard('{ArrowRight}')
        await userEvent.keyboard(' ')
        await waitFor(() =>
            expect(dragHandleOrder()).toEqual([
                'Drag starter to reorder',
                'Drag free to reorder',
                'Drag scale to reorder',
            ])
        )
    },
}

export const SqlVariableEditQuillDate: Story = {
    parameters: {
        pageUrl: urls.variableEdit(DATE_VARIABLE.id),
        testOptions: { waitForSelector: '[data-attr="variable-insights-empty"]', snapshotBrowsers: [] },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvas.getByText('No insights use this variable')).toBeInTheDocument())
        await expect(canvas.getByRole('textbox', { name: 'Name' })).toHaveValue('Start date')
        await expect(canvas.getByRole('spinbutton', { name: 'Amount' })).toHaveValue(7)
        await userEvent.click(canvas.getByRole('button', { name: 'Fixed date' }))
        await waitFor(() => expect(canvas.queryByRole('spinbutton', { name: 'Amount' })).not.toBeInTheDocument())
    },
}

const REGION_QUERY_RESPONSE = {
    results: [
        ['eu', 'Europe'],
        ['us', 'United States'],
    ],
}

export const SqlVariableEditQuillQueryOptions: Story = {
    parameters: {
        pageUrl: urls.variableEdit(QUERY_VARIABLE.id),
        testOptions: { waitForSelector: '[data-attr="variable-insights-empty"]', snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/': REGION_QUERY_RESPONSE,
                '/api/environments/:team_id/query/:kind/': REGION_QUERY_RESPONSE,
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvas.getByText('Loaded')).toBeInTheDocument())
        await expect(canvas.getByText('United States')).toBeInTheDocument()
        await expect(canvas.getByRole('combobox', { name: 'Default value' })).toHaveValue('Europe')
    },
}
