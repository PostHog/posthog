import { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import { FEATURE_FLAGS, STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { expect, userEvent } from 'storybook/test'

import { IngestionWarningV2Summary } from './ingestionWarningsV2Logic'

const WARNINGS: IngestionWarningV2Summary[] = [
    {
        type: 'event_timestamp_in_future',
        category: 'timestamps',
        severity: 'warning',
        count: 1234,
        last_seen: '2023-02-15T14:00:00.000Z',
        sparkline: [
            { timestamp: '2023-02-14T00:00:00.000Z', count: 600 },
            { timestamp: '2023-02-15T00:00:00.000Z', count: 634 },
        ],
        samples: [
            {
                timestamp: '2023-02-15T14:00:00.000Z',
                source: 'ingestion',
                pipeline_step: 'normalize_timestamps',
                event_uuid: '01863e2c-0000-0000-0000-000000000001',
                distinct_id: 'user-1',
                person_id: null,
                group_key: null,
                details: {
                    eventUuid: '01863e2c-0000-0000-0000-000000000001',
                    timestamp: '2023-02-17T14:00:00.000Z',
                    now: '2023-02-15T14:00:00.000Z',
                    result: '2023-02-15T14:00:00.000Z',
                },
            },
        ],
    },
    {
        type: 'cannot_merge_already_identified',
        category: 'person_merging',
        severity: 'error',
        count: 12,
        last_seen: '2023-02-15T10:00:00.000Z',
        sparkline: [{ timestamp: '2023-02-15T00:00:00.000Z', count: 12 }],
        samples: [],
    },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management/Ingestion warnings v2',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-15T16:00:00.000Z',
        pageUrl: urls.ingestionWarningsV2(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/ingestion_warnings_v2/': () => [200, WARNINGS],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const IngestionWarningsV2: Story = {
    parameters: { testOptions: { snapshotBrowsers: [] } },
}

export const IngestionWarningsV2Quill: Story = {
    parameters: {
        featureFlags: [...STORYBOOK_FEATURE_FLAGS, FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { snapshotBrowsers: [] },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const expandButton = await canvas.findByRole(
            'button',
            { name: 'Show event_timestamp_in_future samples' },
            { timeout: 10000 }
        )
        await userEvent.click(expandButton)
        await waitFor(() => expect(canvas.getByText('normalize_timestamps')).toBeInTheDocument())
        await expect(canvas.getByRole('link', { name: 'user-1' })).toBeInTheDocument()
    },
}
