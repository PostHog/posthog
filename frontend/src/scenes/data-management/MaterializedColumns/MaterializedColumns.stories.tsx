import { MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { FEATURE_FLAGS, STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { expect, userEvent } from 'storybook/test'

const SLOTS = [
    {
        id: 'slot-1',
        team: 997,
        property_definition: 101,
        property_definition_details: { id: 101, name: '$browser', property_type: 'String', type: 1 },
        slot_index: 0,
        state: 'READY',
        error_message: null,
        created_at: '2023-01-10T10:00:00Z',
    },
    {
        id: 'slot-2',
        team: 997,
        property_definition: 102,
        property_definition_details: { id: 102, name: 'plan', property_type: 'String', type: 1 },
        slot_index: null,
        state: 'PENDING',
        error_message: null,
        created_at: '2023-01-12T10:00:00Z',
    },
    {
        id: 'slot-3',
        team: 997,
        property_definition: 103,
        property_definition_details: { id: 103, name: 'order_total', property_type: 'Numeric', type: 1 },
        slot_index: 2,
        state: 'ERROR',
        error_message: 'Backfill mutation timed out',
        created_at: '2023-01-13T10:00:00Z',
    },
]

const AVAILABLE_PROPERTIES = [
    { id: 201, name: 'utm_source', property_type: 'String', type: 1 },
    { id: 202, name: 'is_trial', property_type: 'Boolean', type: 1 },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management/Materialized Columns',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-15',
        pageUrl: urls.materializedColumns(),
        featureFlags: [...STORYBOOK_FEATURE_FLAGS, FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { waitForSelector: '[data-attr="materialized-slots-table"]', snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me/': { ...MOCK_DEFAULT_USER, is_staff: true },
                '/api/projects/:team_id/materialized_column_slots/': { results: SLOTS },
                '/api/projects/:team_id/materialized_column_slots/slot_usage/': {
                    team_id: 997,
                    team_name: 'MockHog',
                    used_total: 3,
                    max_slots_per_team: 10,
                    available: 7,
                },
                '/api/projects/:team_id/materialized_column_slots/available_properties/': AVAILABLE_PROPERTIES,
                '/api/projects/:team_id/materialized_column_slots/auto_materialized/': [
                    { column_name: 'mat_$current_url', property_name: '$current_url', table_column: 'properties' },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const MaterializedColumnsQuill: Story = {}

export const MaterializedColumnsQuillAssignSlot: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByRole('button', { name: 'Assign slot' }, { timeout: 10000 }))
        const body = within(canvasElement.ownerDocument.body)
        await body.findByRole('dialog', { name: 'Assign Materialized Column Slot' })
        await userEvent.type(await body.findByPlaceholderText('Search properties...'), 'utm')
        await userEvent.click(await body.findByRole('option', { name: /utm_source/ }))
        await expect(body.getByRole('button', { name: 'Queue for materialization' })).toBeEnabled()
    },
}
