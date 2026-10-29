import { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import { mswDecorator } from '~/mocks/browser'

import { expect, userEvent } from 'storybook/test'

import { BICatalogMetricPicker } from './BICatalogMetricPicker'
import { biCatalogPickerLogic } from './biCatalogPickerLogic'

const meta: Meta<typeof BICatalogMetricPicker> = {
    title: 'Products/Business intelligence/Catalog metric picker',
    component: BICatalogMetricPicker,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/data_catalog/metrics/': ({ request }) => ({
                    count: 3,
                    next: null,
                    results: [
                        {
                            id: 'revenue',
                            name: 'revenue',
                            description: 'Revenue from completed purchases, in USD.',
                            status: 'approved',
                            is_drifted: false,
                            definition: { kind: 'HogQLQuery', query: 'SELECT 42 AS revenue' },
                        },
                        {
                            id: 'purchases',
                            name: 'purchases',
                            description: 'Completed purchases per day.',
                            status: 'proposed',
                            is_drifted: true,
                            definition: { kind: 'HogQLQuery', query: 'SELECT 7 AS purchases' },
                        },
                        {
                            id: 'signups',
                            name: 'signups',
                            description: 'New signups per week.',
                            status: 'proposed',
                            is_drifted: false,
                            definition: { kind: 'TrendsQuery' },
                        },
                    ].filter((metric) => metric.name.includes(new URL(request.url).searchParams.get('search') ?? '')),
                }),
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByRole('button', { name: 'Use a catalog metric' }))
        await waitFor(() => expect(biCatalogPickerLogic.values.metricsLoading).toBe(false))
    },
}
export default meta
type Story = StoryObj<typeof meta>
export const Metrics: Story = {}
export const Empty: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/data_catalog/metrics/': { count: 0, results: [], next: null } },
        }),
    ],
}
export const Error: Story = {
    decorators: [
        mswDecorator({ get: { '/api/projects/:team_id/data_catalog/metrics/': [500, { detail: 'Unavailable' }] } }),
    ],
}
