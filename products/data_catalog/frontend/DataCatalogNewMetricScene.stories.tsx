import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

import { DataCatalogNewMetricScene } from './DataCatalogNewMetricScene'
import { dataCatalogNewMetricSceneLogic, NewMetricFormValues, SqlPreview } from './dataCatalogNewMetricSceneLogic'

const MONTHLY_ACTIVE_USERS: Partial<NewMetricFormValues> = {
    display_name: 'Monthly active users',
    name: 'monthly_active_users',
    definitionType: 'sql',
    sql: 'SELECT count(DISTINCT person_id) AS value\nFROM events\nWHERE timestamp > now() - INTERVAL 30 DAY',
    description: 'Distinct people who did any event in the last 30 days.',
    unit: 'users',
}

const SINGLE_NUMBER: SqlPreview = {
    sql: MONTHLY_ACTIVE_USERS.sql as string,
    columns: ['value'],
    rows: [[12345]],
    hasMore: false,
    warnings: [],
}

const LONG_NAMES: Partial<NewMetricFormValues> = {
    display_name: 'Weekly paying accounts on annual enterprise plans in North America',
    name: 'weekly_paying_accounts_on_annual_enterprise_plans_in_north_america',
    definitionType: 'sql',
    sql: 'SELECT plan, region, count() AS accounts FROM accounts GROUP BY plan, region',
    description: '',
    unit: '',
}

const WEEKLY_SIGNUPS_INSIGHT: Partial<NewMetricFormValues> = {
    display_name: 'Weekly signups',
    name: 'weekly_signups',
    definitionType: 'insight',
    sourceInsightShortId: 'abc123',
    description: 'People who signed up each week.',
    unit: 'signups',
}

const SAVED_INSIGHTS = {
    results: [
        {
            short_id: 'abc123',
            name: 'Weekly signups',
            query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery' } },
        },
        {
            short_id: 'def456',
            name: 'Activation funnel',
            query: { kind: 'InsightVizNode', source: { kind: 'FunnelsQuery' } },
        },
    ],
}

const BREAKDOWN: SqlPreview = {
    sql: LONG_NAMES.sql as string,
    columns: ['plan', 'region', 'accounts'],
    rows: [
        ['enterprise_annual', 'north_america', 412],
        ['enterprise_annual', 'europe', 287],
        ['team_monthly', 'north_america', 1904],
    ],
    hasMore: true,
    warnings: [],
}

function FilledNewMetricScene({
    form,
    preview,
    className,
    queryError,
}: {
    form: Partial<NewMetricFormValues>
    preview: SqlPreview
    className: string
    queryError?: string
}): JSX.Element {
    useEffect(() => {
        dataCatalogNewMetricSceneLogic.actions.setMetricFormValues(form)
        dataCatalogNewMetricSceneLogic.actions.runSqlPreviewSuccess(preview)
        if (queryError) {
            dataCatalogNewMetricSceneLogic.actions.setSqlMetadata({
                query: form.sql,
                errors: [{ message: queryError }],
                warnings: [],
                notices: [],
            })
        }
    }, [form, preview, queryError])

    return (
        <div className={className}>
            <DataCatalogNewMetricScene />
        </div>
    )
}

const meta: Meta = {
    title: 'Products/Data catalog/New metric',
    parameters: { layout: 'padded', viewMode: 'story' },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/data_catalog/metrics/': EMPTY_PAGINATED_RESPONSE,
                '/api/environments/:team_id/insights/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/insights/': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const SqlWithResult: Story = {
    render: () => <FilledNewMetricScene form={MONTHLY_ACTIVE_USERS} preview={SINGLE_NUMBER} className="w-[960px]" />,
}

export const NarrowSceneWithTable: Story = {
    render: () => <FilledNewMetricScene form={LONG_NAMES} preview={BREAKDOWN} className="w-130" />,
}

const QUILL_PARAMETERS = {
    featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE],
    testOptions: { snapshotBrowsers: [] },
}

export const QuillSqlWithResult: Story = {
    parameters: QUILL_PARAMETERS,
    render: () => <FilledNewMetricScene form={MONTHLY_ACTIVE_USERS} preview={SINGLE_NUMBER} className="w-[960px]" />,
}

export const QuillNarrowSceneWithTable: Story = {
    parameters: QUILL_PARAMETERS,
    render: () => <FilledNewMetricScene form={LONG_NAMES} preview={BREAKDOWN} className="w-128" />,
}

export const QuillInsightDefinition: Story = {
    parameters: QUILL_PARAMETERS,
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights/': SAVED_INSIGHTS,
                '/api/projects/:team_id/insights/': SAVED_INSIGHTS,
            },
        }),
    ],
    render: () => <FilledNewMetricScene form={WEEKLY_SIGNUPS_INSIGHT} preview={SINGLE_NUMBER} className="w-[960px]" />,
}

const UNKNOWN_COLUMN_SQL = 'SELECT count(DISTINCT person_idd) AS value\nFROM events'
const UNKNOWN_COLUMN_ERROR = 'Unable to resolve field: person_idd'

export const QuillSqlBlockedByQueryError: Story = {
    parameters: QUILL_PARAMETERS,
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as { query?: { kind?: string; query?: string } }
                    if (body.query?.kind !== 'HogQLMetadata') {
                        return [200, {}]
                    }
                    return [
                        200,
                        {
                            query: body.query.query,
                            isValid: false,
                            errors: [{ message: UNKNOWN_COLUMN_ERROR }],
                            warnings: [],
                            notices: [],
                        },
                    ]
                },
            },
        }),
    ],
    render: () => (
        <FilledNewMetricScene
            form={{ ...MONTHLY_ACTIVE_USERS, sql: UNKNOWN_COLUMN_SQL }}
            preview={SINGLE_NUMBER}
            queryError={UNKNOWN_COLUMN_ERROR}
            className="w-[960px]"
        />
    ),
}
