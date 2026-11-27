import type { Meta, StoryObj } from '@storybook/react'

import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { ErrorListApi } from '../../generated/api.schemas'
import { withWidth } from '../trace/storyFixtures'
import { ErrorsListHost } from './ErrorsListHost'
import {
    ERRORS_URL,
    ERROR_FIRST_SEEN_URL,
    ERROR_NEW_COUNT_URL,
    makeErrorFirstSeen,
    makeErrorFirstSeenList,
    makeErrorListItem,
    makeErrorListPage,
} from './testFixtures'

const PAGE: ErrorListApi = makeErrorListPage([], {
    count: 3,
    counts: { total: 3, increasing: 1, decreasing: 1, maxOccurrences: 128 },
    results: [
        makeErrorListItem({ key: 'error-1' }),
        makeErrorListItem({
            key: 'error-2',
            message: 'TimeoutError: the example-model call took longer than 30 seconds',
            occurrences: 41,
            changeLabel: '-35%',
            changeTone: 'good',
            trend: 'decreasing',
            traces: 40,
            users: 12,
            models: ['example-model-small'],
            series: [9, 8, 7, 6, 5, 4, 2],
        }),
        makeErrorListItem({
            key: 'error-3',
            message: 'ValidationError: the tool call arguments did not match the example_search schema',
            occurrences: 6,
            changeLabel: 'was 0',
            changeTone: 'neutral',
            trend: 'steady',
            traces: 6,
            users: 0,
            models: [],
            series: [0, 0, 0, 0, 0, 2, 4],
        }),
    ],
})

const FIRST_SEEN = {
    [ERROR_FIRST_SEEN_URL]: makeErrorFirstSeenList([
        makeErrorFirstSeen('error-1', { firstSeen: null }),
        makeErrorFirstSeen('error-2'),
        makeErrorFirstSeen('error-3', { firstSeen: '2026-09-06T14:00:00Z', isNew: true }),
    ]),
}

const meta: Meta<typeof ErrorsListHost> = {
    title: 'Scenes-App/AI observability/Errors/Errors list',
    component: ErrorsListHost,
    decorators: [mswDecorator({})],
    parameters: {
        msw: { mocks: { get: { [ERRORS_URL]: PAGE, [ERROR_NEW_COUNT_URL]: { count: 1 } }, post: FIRST_SEEN } },
        mockDate: '2026-09-08T12:00:00Z',
        pageUrl: urls.aiObservabilityErrors(),
        testOptions: { snapshotBrowsers: [], waitForSelector: 'text=Sep 6, 2026' },
    },
}
export default meta

type Story = StoryObj<typeof ErrorsListHost>

export const Rows: Story = {}

export const FirstSeenAndNewCountFailed: Story = {
    parameters: {
        msw: {
            mocks: {
                get: { [ERROR_NEW_COUNT_URL]: () => [500, { detail: 'New count read failed' }] },
                post: { [ERROR_FIRST_SEEN_URL]: () => [500, { detail: 'First seen read failed' }] },
            },
        },
        testOptions: { snapshotBrowsers: [], waitForSelector: '[role="img"][aria-label^="Couldn"]' },
    },
}

export const NothingCaptured: Story = {
    parameters: {
        msw: { mocks: { get: { [ERRORS_URL]: makeErrorListPage([], { nothingCaptured: true }) } } },
        testOptions: { snapshotBrowsers: [], waitForSelector: 'text=No errors captured yet' },
    },
}

export const RangeTooLong: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    [ERRORS_URL]: () => [
                        422,
                        { code: 'range_too_long', detail: 'Pick a date range of 90 days or less for errors.' },
                    ],
                },
            },
        },
        testOptions: { snapshotBrowsers: [], waitForSelector: 'text=Pick a date range' },
    },
}

export const NarrowContainer: Story = {
    decorators: [withWidth(360)],
}
