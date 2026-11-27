import type { Meta, StoryObj } from '@storybook/react'

import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { ToolListApi } from '../../generated/api.schemas'
import { withWidth } from '../trace/storyFixtures'
import {
    TOOLS_URL,
    TOOL_TRACE_SHARES_URL,
    makeToolListItem,
    makeToolListPage,
    makeToolTraceShares,
} from './testFixtures'
import { ToolsListHost } from './ToolsListHost'

const PAGE: ToolListApi = makeToolListPage([], {
    count: 3,
    counts: { total: 3, failing: 1, maxCalls: 1240 },
    results: [
        makeToolListItem({ key: 'tool-1' }),
        makeToolListItem({
            key: 'tool-2',
            name: 'get_weather_forecast',
            calls: 410,
            changeLabel: '-12%',
            traces: 380,
            failureRate: 0.004,
            failures: 2,
            isFailing: false,
            onlyToolShare: 0.81,
            series: [70, 65, 60, 58, 55, 52, 50],
        }),
        makeToolListItem({
            key: 'tool-3',
            name: 'send_example_email',
            calls: 36,
            changeLabel: 'was 0',
            traces: 30,
            failureRate: null,
            failures: null,
            failureState: 'not_captured',
            isFailing: false,
            onlyToolShare: 0,
            series: [0, 0, 0, 0, 0, 12, 24],
        }),
    ],
})

const meta: Meta<typeof ToolsListHost> = {
    title: 'Scenes-App/AI observability/Tools/Tools list',
    component: ToolsListHost,
    decorators: [mswDecorator({}), withWidth(360)],
    parameters: {
        msw: {
            mocks: {
                get: { [TOOLS_URL]: PAGE },
                post: {
                    [TOOL_TRACE_SHARES_URL]: makeToolTraceShares([
                        ['tool-1', 0.42],
                        ['tool-2', 0.26],
                        ['tool-3', 0.02],
                    ]),
                },
            },
        },
        mockDate: '2026-09-08T12:00:00Z',
        pageUrl: urls.aiObservabilityTools(),
        testOptions: { snapshotBrowsers: [], waitForSelector: 'text=send_example_email' },
    },
}
export default meta

type Story = StoryObj<typeof ToolsListHost>

export const NarrowContainer: Story = {}

export const TraceSharesFailed: Story = {
    parameters: {
        msw: { mocks: { post: { [TOOL_TRACE_SHARES_URL]: () => [422, { detail: 'Trace shares read failed' }] } } },
        testOptions: { snapshotBrowsers: [], waitForSelector: '[role="img"][aria-label^="Couldn"]' },
    },
}
