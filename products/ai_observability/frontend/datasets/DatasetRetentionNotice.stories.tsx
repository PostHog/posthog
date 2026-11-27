import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor, within } from '@testing-library/dom'
import { router } from 'kea-router'

import { mswDecorator } from '~/mocks/browser'

import { expect } from 'storybook/test'

import type { DatasetRetentionEntryApi, DatasetRetentionReadApi } from '../generated/api.schemas'
import { datasetRetentionLogic } from './datasetRetentionLogic'
import { DatasetRetentionNotice } from './DatasetRetentionNotice'

const entries: DatasetRetentionEntryApi[] = [
    {
        dataset_id: 'example-support',
        dataset_name: 'Support answers',
        dataset_archived: false,
        revision: null,
        expires_at: '2024-01-16T12:00:00Z',
    },
    {
        dataset_id: 'example-prompts',
        dataset_name: 'Archived prompts',
        dataset_archived: true,
        revision: null,
        expires_at: '2024-01-18T12:00:00Z',
    },
    {
        dataset_id: 'example-pricing',
        dataset_name: 'Pricing questions',
        dataset_archived: false,
        revision: null,
        expires_at: '2024-01-19T12:00:00Z',
    },
]

const meta: Meta<typeof DatasetRetentionNotice> = {
    title: 'Products/AI observability/Dataset retention',
    component: DatasetRetentionNotice,
    parameters: { mockDate: '2024-01-15T12:00:00Z', testOptions: { snapshotBrowsers: [] } },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/datasets/': { count: 0, results: [] },
                '/api/projects/:team/datasets/retention/': ({ request }): DatasetRetentionReadApi => {
                    const params = new URL(request.url).searchParams
                    const revisions = params.get('kind') === 'revisions'
                    const results = revisions
                        ? Array.from({ length: 8 }, (_, i) => ({ ...entries[i % entries.length], revision: i + 1 }))
                        : entries
                    const offset = Number(params.get('offset') ?? 0)
                    const limit = Number(params.get('limit') ?? 5)
                    return {
                        datasets_count: 3,
                        revisions_count: 8,
                        count: revisions ? 8 : 3,
                        results: results.slice(offset, offset + limit),
                    }
                },
            },
        }),
        (Story) => (
            <div className="@container/datasets">
                <Story />
            </div>
        ),
    ],
    play: async ({ canvasElement }) => {
        await within(canvasElement).findByText('3 datasets and 8 older revisions expiring within 7 days')
    },
}
export default meta
type Story = StoryObj<typeof DatasetRetentionNotice>

export const Collapsed: Story = {}

export const Expanded: Story = {
    play: async ({ canvasElement }) => {
        fireEvent.click(await within(canvasElement).findByText('Review'))
        await within(canvasElement).findByText('Support answers')
    },
}

export const Revisions: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        fireEvent.click(await canvas.findByText('Review'))
        fireEvent.click(await canvas.findByText('Older revisions (8)'))
        await canvas.findByText('· Revision 1')

        const initialLocation = { ...router.values.location }
        fireEvent.click(canvas.getByRole('button', { name: 'Next page' }))
        await canvas.findByText('· Revision 6')
        await expect(router.values.location).toEqual(initialLocation)

        fireEvent.click(canvas.getByRole('button', { name: 'Previous page' }))
        await canvas.findByText('· Revision 1')
        await expect(router.values.location).toEqual(initialLocation)
    },
}

export const Failed: Story = {
    decorators: [
        mswDecorator({ get: { '/api/projects/:team/datasets/retention/': [500, { detail: 'Unavailable' }] } }),
    ],
    play: async ({ canvasElement }) => {
        await waitFor(() => expect(datasetRetentionLogic.values.retentionError).toBe(true))
        await expect(within(canvasElement).queryAllByText('Retry')).toHaveLength(0)
    },
}

export const RefreshFailed: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/datasets/retention/': ({ request }) =>
                    Number(new URL(request.url).searchParams.get('offset')) > 0
                        ? [500, { detail: 'Unavailable' }]
                        : {
                              datasets_count: 6,
                              revisions_count: 0,
                              count: 6,
                              results: Array.from({ length: 5 }, (_, i) => ({
                                  ...entries[0],
                                  dataset_id: `example-dataset-${i}`,
                                  dataset_name: `Example dataset ${i + 1}`,
                              })),
                          },
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        fireEvent.click(await canvas.findByText('Review'))
        await canvas.findByText('Example dataset 1')
        fireEvent.click(canvas.getByRole('button', { name: 'Next page' }))
        await canvas.findByText("Couldn't refresh dataset retention. Showing the last known deadlines. Try again.")
        await expect(canvas.getByText('Example dataset 1')).toBeVisible()
        fireEvent.click(canvas.getByText('Hide'))
        await waitFor(() => expect(canvas.queryAllByText('Retry')).toHaveLength(0))
        await expect(canvas.getByText('6 datasets expiring within 7 days')).toBeVisible()
    },
}
