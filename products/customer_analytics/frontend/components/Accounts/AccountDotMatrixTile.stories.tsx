import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import type { AccountActivityMatrixResult } from '~/queries/schema/schema-general'

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

function queryResponse(results: AccountActivityMatrixResult): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        post: {
            '/api/environments/:team_id/query/': { results },
            '/api/environments/:team_id/query/:query_kind/': { results },
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
