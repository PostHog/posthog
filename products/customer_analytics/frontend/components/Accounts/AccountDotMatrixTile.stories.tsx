import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import type { AccountActivityMatrixResult, BookActivityMatrixResult } from '~/queries/schema/schema-general'

import { BOOK_ACTIVITY_MATRIX_MOCK } from '../../__mocks__/bookActivityMatrixMock'
import { EMPTY_ACCOUNT_ACTIVITY_MATRIX } from './accountActivityMatrix'
import { AccountDotMatrixTile } from './AccountDotMatrixTile'

const WEEKS = [
    '2026-09-06',
    '2026-09-13',
    '2026-09-20',
    '2026-09-27',
    '2026-10-04',
    '2026-10-11',
    '2026-10-18',
    '2026-10-25',
]
const PEOPLE = ['ana', 'bo', 'cy', 'dee', 'eli']
const METRICS = ['Insights viewed', 'Replays watched', 'Flags changed', 'Surveys launched']

const ACTIVITY: AccountActivityMatrixResult = {
    rows: PEOPLE.map((name) => ({ key: `person-${name}`, label: `${name}@example.com` })),
    columns: WEEKS.map((key, index) => ({ key, partial: index === WEEKS.length - 1 })),
    series: METRICS.map((label, index) => ({ key: `metric-${index}`, label })),
    data: PEOPLE.flatMap((name, personIndex) =>
        WEEKS.flatMap((week, weekIndex) =>
            METRICS.map((_, metricIndex) => ({
                row: `person-${name}`,
                column: week,
                series: `metric-${metricIndex}`,
                value: (personIndex + weekIndex * 2 + metricIndex * 3) % 5 < 2 ? 0 : personIndex + weekIndex + 1,
            }))
        )
    ).filter(({ value }) => value > 0),
    truncated: false,
    skippedMetricIds: [],
}

function queryResponse(
    results: AccountActivityMatrixResult | BookActivityMatrixResult | unknown[][],
    columns?: string[]
): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        post: {
            '/api/environments/:team_id/query/': { results, columns },
            '/api/environments/:team_id/query/:query_kind/': { results, columns },
        },
    })
}

const meta: Meta<typeof AccountDotMatrixTile> = {
    title: 'Customer Analytics/Account views/Dot matrix',
    component: AccountDotMatrixTile,
    args: { instanceId: 'dot-matrix-example', accountId: 'account-1' },
    parameters: {
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS_DOT_MATRIX],
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="account-dot-matrix-tile"]' },
    },
    decorators: [
        (Story) => (
            <div className="w-128">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof AccountDotMatrixTile>

export const PersonActivity: Story = {
    decorators: [queryResponse(ACTIVITY)],
}

export const NoUsageMetrics: Story = {
    decorators: [queryResponse({ ...EMPTY_ACCOUNT_ACTIVITY_MATRIX, emptyReason: 'no_metrics' })],
}

export const Unconfigured: Story = {
    args: { initialConfig: { source: null } },
}

export const ProductUsage: Story = {
    args: { initialConfig: { source: { kind: 'product_usage' } } },
    decorators: [
        queryResponse({
            ...BOOK_ACTIVITY_MATRIX_MOCK,
            rows: BOOK_ACTIVITY_MATRIX_MOCK.rows.slice(0, 1),
            data: BOOK_ACTIVITY_MATRIX_MOCK.data.filter(({ row }) => row === BOOK_ACTIVITY_MATRIX_MOCK.rows[0].key),
            combinations: BOOK_ACTIVITY_MATRIX_MOCK.combinations.filter(
                ({ row }) => row === BOOK_ACTIVITY_MATRIX_MOCK.rows[0].key
            ),
        }),
    ],
}

export const CustomQuery: Story = {
    args: {
        initialConfig: {
            source: {
                kind: 'hogql',
                query: "SELECT 'Example' AS row, 'Week 1' AS column, 4 AS value",
                mapping: { row: 'row', column: 'column', value: 'value' },
            },
        },
    },
    decorators: [queryResponse([['Example', 'Week 1', 4]], ['row', 'column', 'value'])],
}

export const LoadFailure: Story = {
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/': [500, { detail: 'Could not load activity.' }],
                '/api/environments/:team_id/query/:query_kind/': [500, { detail: 'Could not load activity.' }],
            },
        }),
    ],
}
