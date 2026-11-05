import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, within } from '@testing-library/dom'

import { mswDecorator } from '~/mocks/browser'

import type { DatasetRetentionEntryApi, DatasetRetentionReadApi } from '../generated/api.schemas'
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
        fireEvent.click(await within(canvasElement).findByText('Review'))
        fireEvent.click(await within(canvasElement).findByText('Older revisions (8)'))
        await within(canvasElement).findByText('· Revision 1')
    },
}

export const Failed: Story = {
    decorators: [
        mswDecorator({ get: { '/api/projects/:team/datasets/retention/': [500, { detail: 'Unavailable' }] } }),
    ],
    play: async ({ canvasElement }) => {
        await within(canvasElement).findByText("Couldn't check dataset retention. Try again.")
    },
}
