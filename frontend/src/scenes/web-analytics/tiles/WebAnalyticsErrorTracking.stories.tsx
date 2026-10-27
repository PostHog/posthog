import type { Meta, StoryObj } from '@storybook/react'

import {
    errorTrackingQueryResponse,
    errorTrackingTypeIssue,
} from '@posthog/products-error-tracking/frontend/__mocks__/error_tracking_query'
import { errorTrackingQuery } from '@posthog/products-error-tracking/frontend/queries'

import { ErrorTrackingTile, TileId } from 'scenes/web-analytics/common'

import { mswDecorator } from '~/mocks/browser'
import { ErrorTrackingQueryResponse } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

import { WebAnalyticsErrorTrackingTile } from './WebAnalyticsErrorTracking'

const tile: ErrorTrackingTile = {
    kind: 'error_tracking',
    tileId: TileId.ERROR_TRACKING,
    layout: {},
    query: errorTrackingQuery({
        orderBy: 'users',
        dateRange: { date_from: '-7d', date_to: null },
        filterTestAccounts: false,
        filterGroup: { type: FilterLogicalOperator.And, values: [] },
        columns: ['error', 'users', 'occurrences', 'last_seen'],
        limit: 4,
    }),
}

const ISSUES: { name: string; description: string; users: number; occurrences: number }[] = [
    {
        name: 'TypeError',
        description: "Cannot read properties of undefined (reading 'onLCP')",
        users: 42,
        occurrences: 310,
    },
    {
        name: 'Non-OK response',
        description: 'The billing request returned an unsuccessful response.',
        users: 17,
        occurrences: 96,
    },
    { name: 'ChunkLoadError', description: 'Loading chunk 482 failed.', users: 5, occurrences: 12 },
]

const ISSUES_RESPONSE: ErrorTrackingQueryResponse = {
    ...errorTrackingQueryResponse,
    results: ISSUES.map(({ name, description, users, occurrences }, index) => ({
        ...errorTrackingQueryResponse.results[0],
        ...errorTrackingTypeIssue,
        id: `01890a1b-2c3d-4e4f-8a9b-0c1d2e3f4a${index}0`,
        name,
        description,
        last_seen: '2023-01-31T12:00:00Z',
        aggregations: { ...errorTrackingQueryResponse.results[0].aggregations!, users, occurrences },
    })),
}

const meta: Meta = {
    title: 'Web Analytics/Tiles/Error tracking',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2023-02-01',
        testOptions: { waitForLoadersToDisappear: true },
    },
    render: (_, { parameters }) => (
        <div className={parameters.tileWidthClass ?? 'w-[36rem]'}>
            <WebAnalyticsErrorTrackingTile tile={tile} />
        </div>
    ),
}
export default meta

type Story = StoryObj

export const NotSetUp: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/environments/:team_id/error_tracking/issues/exists/': [200, { exists: false }] },
            post: { '/api/environments/:team_id/query/:kind/': () => new Promise<never>(() => {}) },
        }),
    ],
}

export const NotSetUpNarrow: Story = {
    ...NotSetUp,
    parameters: { tileWidthClass: 'w-80' },
}

export const WithIssues: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/environments/:team_id/error_tracking/issues/exists/': [200, { exists: true }] },
            post: { '/api/environments/:team_id/query/:kind/': [200, ISSUES_RESPONSE] },
        }),
    ],
}

export const SetUpWithoutIssues: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/environments/:team_id/error_tracking/issues/exists/': [200, { exists: true }] },
            post: { '/api/environments/:team_id/query/:kind/': [200, { ...errorTrackingQueryResponse, results: [] }] },
        }),
    ],
}
