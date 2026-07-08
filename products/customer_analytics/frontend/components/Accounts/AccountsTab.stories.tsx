import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { MockResolverInfo } from '~/mocks/utils'

const QUERY_ENDPOINT = '/api/environments/:team_id/query/:kind/'
const ACCOUNT_RETRIEVE_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/'
const ACCOUNT_NOTEBOOKS_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/notebooks/'
const WAREHOUSE_VIEW_LINK_ENDPOINT = 'api/environments/:team_id/warehouse_view_link/'
const INSIGHTS_ENDPOINT = 'api/environments/:team_id/insights/'

type AccountNameCell = { name: string; external_id: string | null; id: string }
type AccountRoleCell = [number, string] | null
type AccountRow = [AccountNameCell, string[], number, AccountRoleCell, AccountRoleCell, AccountRoleCell]

function buildAccountsQueryResponse(rows: AccountRow[]): Record<string, unknown> {
    return {
        kind: 'AccountsQuery',
        columns: ['name', 'tag_names', 'notebook_count', 'csm', 'account_executive', 'account_owner'],
        results: rows,
        types: [],
        hogql: '',
        timings: [],
        modifiers: {},
        hasMore: false,
        limit: 100,
        offset: 0,
    }
}

const SAMPLE_ROWS: AccountRow[] = [
    [
        { name: 'Acme Inc', external_id: 'cust_acme_001', id: 'acc-1' },
        ['enterprise', 'priority'],
        0,
        [1, 'alice@posthog.com'],
        [2, 'bob@posthog.com'],
        null,
    ],
    [{ name: 'Globex', external_id: 'cust_globex_002', id: 'acc-2' }, [], 0, null, null, null],
    [
        { name: 'Hooli', external_id: null, id: 'acc-3' },
        ['scaleup'],
        0,
        [1, 'alice@posthog.com'],
        null,
        [3, 'carol@posthog.com'],
    ],
]

const SINGLE_ROW: AccountRow[] = [
    [
        { name: 'Acme Inc', external_id: 'cust_acme_001', id: 'acc-1' },
        ['enterprise', 'priority'],
        1,
        [1, 'alice@posthog.com'],
        [2, 'bob@posthog.com'],
        null,
    ],
]

const ACCOUNT_WITH_LINKS = {
    id: 'acc-1',
    name: 'Acme Inc',
    external_id: 'cust_acme_001',
    properties: {
        billing_id: 'cus_acme_123',
        slack_channel_id: 'C0123456789',
        usage_dashboard_link: 'https://us.posthog.com/project/2/dashboard/12345',
    },
    tags: [],
    notebooks: [],
    created_at: '2026-05-15T10:30:00Z',
    created_by: null,
    updated_at: '2026-05-15T10:30:00Z',
}

const ACCOUNT_WITHOUT_LINKS = {
    id: 'acc-1',
    name: 'Acme Inc',
    external_id: null,
    properties: {},
    tags: [],
    notebooks: [],
    created_at: '2026-05-15T10:30:00Z',
    created_by: null,
    updated_at: '2026-05-15T10:30:00Z',
}

const EMPTY_INSIGHTS = { count: 0, next: null, previous: null, results: [] }

function insightsResponse(insight: Record<string, unknown>): Record<string, unknown> {
    return { count: 1, next: null, previous: null, results: [insight] }
}

const BILLING_VARIABLES = {
    'var-org': { variableId: 'var-org', code_name: 'billing_org_id', value: '' },
    'var-start': { variableId: 'var-start', code_name: 'billing_start_date', value: '2026-04-21' },
    'var-end': { variableId: 'var-end', code_name: 'billing_end_date', value: '2026-05-21' },
}

const USAGE_INSIGHT = {
    id: 9050931,
    short_id: 'fiJDsKLp',
    name: 'Billing usage by type (warehouse)',
    filters: {},
    saved: true,
    deleted: false,
    query: {
        kind: 'DataVisualizationNode',
        display: 'ActionsLineGraph',
        source: {
            kind: 'HogQLQuery',
            query: 'SELECT date, ... FROM postgres.prod.billing_usagereport',
            variables: BILLING_VARIABLES,
        },
    },
}

const USAGE_QUERY_RESPONSE = {
    error: '',
    hasMore: false,
    is_cached: true,
    query_status: null,
    columns: ['date', 'Events', 'Recordings'],
    types: [
        ['date', 'Date'],
        ['Events', 'Nullable(Float64)'],
        ['Recordings', 'Nullable(Float64)'],
    ],
    results: [
        ['2026-05-01', 1200, 30],
        ['2026-05-08', 1800, 45],
        ['2026-05-15', 1500, 38],
        ['2026-05-21', 2100, 52],
    ],
}

// Dispatches the shared query endpoint: account rows for the list, billing chart data for the embedded insight.
function mockAccountsAndBillingQuery(
    rows: AccountRow[],
    billingResponse: Record<string, unknown>
): (info: MockResolverInfo) => Promise<[number, unknown] | undefined> {
    return async ({ request }) => {
        const body = (await request.json()) as { query?: { kind?: string } }
        const kind = body?.query?.kind
        if (kind === 'AccountsQuery') {
            return [200, buildAccountsQueryResponse(rows)]
        }
        if (kind === 'HogQLQuery') {
            return [200, billingResponse]
        }
        return undefined
    }
}

// Billing tab stories share the same account + notebooks mocks; they differ only in the insight and query responses.
function billingTabDecorators(
    insightsGet: Record<string, unknown>,
    queryPost: (info: MockResolverInfo) => Promise<[number, unknown] | undefined>
): ReturnType<typeof mswDecorator>[] {
    return [
        mswDecorator({
            get: {
                [ACCOUNT_RETRIEVE_ENDPOINT]: ACCOUNT_WITH_LINKS,
                [ACCOUNT_NOTEBOOKS_ENDPOINT]: { count: 0, next: null, previous: null, results: [] },
                [INSIGHTS_ENDPOINT]: insightsGet,
            },
            post: {
                [QUERY_ENDPOINT]: queryPost,
            },
        }),
    ]
}

// Expanding a row mounts UsefulLinks (loads the account async) and the notes table
// (loads notebooks async). Both start as skeletons and resolve later, which changes
// the expansion's width and height. Awaiting the settled content here keeps the
// snapshot deterministic — otherwise it races the loads and the Useful links sidebar
// is sometimes absent, sometimes present (the flaky ~7% height/width diff).
async function expandFirstRow(canvasElement: HTMLElement, notesLoadedText: string): Promise<void> {
    const canvas = within(canvasElement)
    await userEvent.click(await canvas.findByTitle('Show more'))
    await canvas.findByText('Useful links')
    await canvas.findByText('Organization')
    await canvas.findByText(notesLoadedText)
}

// Expands the first row and switches to a billing tab. Awaits the settled sidebar first to avoid layout races.
async function expandAndOpenTab(canvasElement: HTMLElement, tab: 'Usage' | 'Spend'): Promise<void> {
    const canvas = within(canvasElement)
    await userEvent.click(await canvas.findByTitle('Show more'))
    await canvas.findByText('Useful links')
    await canvas.findByText('Organization')
    await userEvent.click(await canvas.findByRole('tab', { name: tab }))
}

// The snapshot fires well after `play` (page-ready waits, forced reflows, a dispatched resize),
// and the meta-level waitForSelector is satisfied by a collapsed table. Gating the snapshot on the
// expanded-row content turns a lost expansion into a retry instead of a flaky collapsed capture.
const EXPANDED_ROW_TEST_OPTIONS = {
    waitForSelector: ['[data-attr="accounts-refresh"]', '[data-attr="account-expansion"]'],
}

function mockAccountsQuery(rows: AccountRow[]): (info: MockResolverInfo) => Promise<[number, unknown] | undefined> {
    return async ({ request }) => {
        const body = (await request.json()) as { query?: { kind?: string } }
        const kind = body?.query?.kind
        if (kind === 'AccountsQuery') {
            return [200, buildAccountsQueryResponse(rows)]
        }
        return undefined
    }
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Customer Analytics/Accounts',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-05-21',
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS, FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP],
        pageUrl: urls.customerAnalyticsAccounts(),
        testOptions: {
            waitForSelector: '[data-attr="accounts-refresh"]',
        },
    },
    // NB: no QUERY_ENDPOINT mock here — every story registers exactly one query handler.
    // Meta- and story-level decorators both worker.use() the same path, and their precedence
    // can flip mid-story, so a meta-level query mock intermittently shadows the story's and
    // answers billing/chart queries with an empty 200 (breaking the Usage tab canvas).
    decorators: [
        mswDecorator({
            get: {
                [WAREHOUSE_VIEW_LINK_ENDPOINT]: { count: 0, next: null, previous: null, results: [] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    render: () => <App />,
    decorators: [
        mswDecorator({
            post: {
                [QUERY_ENDPOINT]: mockAccountsQuery(SAMPLE_ROWS),
            },
        }),
    ],
}

export const Empty: Story = {
    render: () => <App />,
    decorators: [
        mswDecorator({
            post: {
                [QUERY_ENDPOINT]: mockAccountsQuery([]),
            },
        }),
    ],
}

// CUSTOMER_ANALYTICS must stay enabled (the outer scene gate) so we get past it;
// without CUSTOMER_ANALYTICS_CSP the accounts URL is treated as a 404.
export const FeatureGateOff: Story = {
    render: () => <App />,
    parameters: {
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS],
        testOptions: {
            waitForSelector: '[data-attr="not-found-page"]',
        },
    },
    decorators: [
        mswDecorator({
            post: {
                [QUERY_ENDPOINT]: mockAccountsQuery(SAMPLE_ROWS),
            },
        }),
    ],
}

export const RowExpandedEmpty: Story = {
    render: () => <App />,
    parameters: { testOptions: EXPANDED_ROW_TEST_OPTIONS },
    decorators: [
        mswDecorator({
            get: {
                [ACCOUNT_RETRIEVE_ENDPOINT]: ACCOUNT_WITH_LINKS,
                [ACCOUNT_NOTEBOOKS_ENDPOINT]: { count: 0, next: null, previous: null, results: [] },
            },
            post: {
                [QUERY_ENDPOINT]: mockAccountsQuery(SINGLE_ROW),
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await expandFirstRow(canvasElement, 'No notes linked to this account yet.')
    },
}

export const RowExpandedWithNote: Story = {
    render: () => <App />,
    parameters: { testOptions: EXPANDED_ROW_TEST_OPTIONS },
    decorators: [
        mswDecorator({
            get: {
                [ACCOUNT_RETRIEVE_ENDPOINT]: ACCOUNT_WITH_LINKS,
                [ACCOUNT_NOTEBOOKS_ENDPOINT]: {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: '11111111-1111-1111-1111-111111111111',
                            short_id: 'abc12345',
                            title: 'Q2 expansion call',
                            content: null,
                            text_content:
                                'Discussed expansion plans for Q2. They want to add the data warehouse integration and roll out session replay to their EU team. Decision-makers: VP Eng (Priya) and CTO (Marco). Follow-up scheduled for next week to scope pricing.',
                            created_at: '2026-05-15T10:30:00Z',
                            created_by: {
                                id: 1,
                                uuid: '00000000-0000-0000-0000-000000000001',
                                email: 'alice@posthog.com',
                                first_name: 'Alice',
                                last_name: 'Anderson',
                                is_email_verified: true,
                            },
                            last_modified_at: '2026-05-15T10:30:00Z',
                            last_modified_by: {
                                id: 1,
                                uuid: '00000000-0000-0000-0000-000000000001',
                                email: 'alice@posthog.com',
                                first_name: 'Alice',
                                last_name: 'Anderson',
                                is_email_verified: true,
                            },
                        },
                    ],
                },
            },
            post: {
                [QUERY_ENDPOINT]: mockAccountsQuery(SINGLE_ROW),
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await expandFirstRow(canvasElement, 'Q2 expansion call')
    },
}

export const RowExpandedLinksDisabled: Story = {
    render: () => <App />,
    parameters: { testOptions: EXPANDED_ROW_TEST_OPTIONS },
    decorators: [
        mswDecorator({
            get: {
                [ACCOUNT_RETRIEVE_ENDPOINT]: ACCOUNT_WITHOUT_LINKS,
                [ACCOUNT_NOTEBOOKS_ENDPOINT]: { count: 0, next: null, previous: null, results: [] },
            },
            post: {
                [QUERY_ENDPOINT]: mockAccountsQuery(SINGLE_ROW),
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await expandFirstRow(canvasElement, 'No notes linked to this account yet.')
    },
}

export const RowExpandedUsageNotFound: Story = {
    render: () => <App />,
    parameters: {
        testOptions: {
            waitForSelector: ['[data-attr="accounts-refresh"]', '[data-attr="account-billing-insight-not-found"]'],
        },
    },
    decorators: billingTabDecorators(EMPTY_INSIGHTS, mockAccountsQuery(SINGLE_ROW)),
    play: async ({ canvasElement }) => {
        await expandAndOpenTab(canvasElement, 'Usage')
        await within(canvasElement).findByText('No billing usage insight here')
    },
}

export const RowExpandedUsagePopulated: Story = {
    render: () => <App />,
    parameters: {
        testOptions: {
            waitForSelector: ['[data-attr="accounts-refresh"]', '.DataVisualization canvas'],
        },
    },
    decorators: billingTabDecorators(
        insightsResponse(USAGE_INSIGHT),
        mockAccountsAndBillingQuery(SINGLE_ROW, USAGE_QUERY_RESPONSE)
    ),
    play: async ({ canvasElement }) => {
        await expandAndOpenTab(canvasElement, 'Usage')
    },
}
