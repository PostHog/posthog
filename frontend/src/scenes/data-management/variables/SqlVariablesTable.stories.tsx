import { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import { FEATURE_FLAGS, STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { Variable } from '~/queries/nodes/DataVisualization/types'

import { expect, userEvent } from 'storybook/test'

const MOCK_VARIABLES: Variable[] = [
    { id: 'variable-1', name: 'Start date', code_name: 'start_date', type: 'Date', default_value: '-7d' },
    { id: 'variable-2', name: 'Country', code_name: 'country', type: 'String', default_value: 'GB' },
    { id: 'variable-3', name: 'Minimum order', code_name: 'minimum_order', type: 'Number', default_value: 50 },
    {
        id: 'variable-4',
        name: 'Include internal',
        code_name: 'include_internal',
        type: 'Boolean',
        default_value: false,
    },
    { id: 'variable-5', name: 'Plan', code_name: 'plan', type: 'List', values: ['free', 'paid'], default_value: '' },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management/SQL Variables',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-15',
        pageUrl: urls.variables(),
        featureFlags: [...STORYBOOK_FEATURE_FLAGS, FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { waitForSelector: '[data-attr="sql-variables-table"]', snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/insight_variables/': toPaginatedResponse(MOCK_VARIABLES),
                '/api/environments/:team_id/insight_variables/': toPaginatedResponse(MOCK_VARIABLES),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const SqlVariablesQuill: Story = {}

const REGION_COUNT = 20

const MANY_VARIABLES: Variable[] = Array.from({ length: 30 }, (_, index) => {
    const isRegion = index < REGION_COUNT
    const number = isRegion ? index + 1 : index - REGION_COUNT + 1
    return {
        id: `variable-many-${index}`,
        name: `${isRegion ? 'Region' : 'Plan'} ${String(number).padStart(2, '0')}`,
        code_name: `${isRegion ? 'region' : 'plan'}_${number}`,
        type: 'String',
        default_value: '',
    }
})

export const SqlVariablesQuillSearchToOnePage: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/insight_variables/': toPaginatedResponse(MANY_VARIABLES),
                '/api/environments/:team_id/insight_variables/': toPaginatedResponse(MANY_VARIABLES),
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const rows = (): number => canvasElement.querySelectorAll('[data-attr="sql-variables-table"] tbody tr').length
        await waitFor(() => expect(rows()).toBe(25))
        await userEvent.type(canvas.getByRole('searchbox', { name: 'Search variables' }), 'Region')
        // A search that fits one page shows every match, not the first ten.
        await waitFor(() => expect(rows()).toBe(REGION_COUNT))
    },
}
