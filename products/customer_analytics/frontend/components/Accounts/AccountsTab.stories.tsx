import { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { MockResolverInfo } from '~/mocks/utils'

const QUERY_ENDPOINT = '/api/environments/:team_id/query/:kind/'
const ACCOUNT_RETRIEVE_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/'
const ACCOUNT_NOTEBOOKS_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/notebooks/'
const ACCOUNT_RELATIONSHIPS_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/relationships/'
const RELATIONSHIP_DEFINITIONS_ENDPOINT = 'api/projects/:team_id/account_relationship_definitions/'
const ORGANIZATION_MEMBERS_ENDPOINT = 'api/projects/:team_id/organization_members/'
const WAREHOUSE_VIEW_LINK_ENDPOINT = 'api/environments/:team_id/warehouse_view_link/'
const INSIGHTS_ENDPOINT = 'api/environments/:team_id/insights/'

type AccountNameCell = { name: string; external_id: string | null; id: string }
// Active assignee user ids from the relationships lazy join. Ids 178 and 202 match
// the default org-members mock so the cells resolve to john.doe / jane.mcdoe.
type AccountRelationshipCell = number[]
type AccountRow = [
    AccountNameCell,
    string[],
    number,
    AccountRelationshipCell,
    AccountRelationshipCell,
    AccountRelationshipCell,
]

const RELATIONSHIP_DEFINITIONS = {
    count: 3,
    next: null,
    previous: null,
    results: [
        { id: 'def-csm', name: 'CSM', description: null, is_single_holder: true },
        { id: 'def-ae', name: 'Account executive', description: null, is_single_holder: true },
        { id: 'def-owner', name: 'Account owner', description: null, is_single_holder: true },
    ],
}

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
    [{ name: 'Acme Inc', external_id: 'cust_acme_001', id: 'acc-1' }, ['enterprise', 'priority'], 0, [178], [202], []],
    [{ name: 'Globex', external_id: 'cust_globex_002', id: 'acc-2' }, [], 0, [], [], []],
    [{ name: 'Hooli', external_id: null, id: 'acc-3' }, ['scaleup'], 0, [178], [], [202]],
]

const SINGLE_ROW: AccountRow[] = [
    [{ name: 'Acme Inc', external_id: 'cust_acme_001', id: 'acc-1' }, ['enterprise', 'priority'], 1, [178], [202], []],
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

// Every fetch the expansion fires must be mocked (even if empty), because AccountNotebooksExpansion
// eagerly mounts the related-users, relationships, and usage/spend billing logics up front. An
// unhandled fetch passes through msw to the static storybook server and errors out, and the failure
// re-render can collapse the expansion — making [data-attr="account-expansion"] disappear so the
// post-play waitForSelector times out. The related-users failure also pops an error toast, which the
// snapshot's loader wait can trip over.
const EXPANDED_ROW_FETCH_MOCKS = {
    [INSIGHTS_ENDPOINT]: EMPTY_INSIGHTS,
    [ORGANIZATION_MEMBERS_ENDPOINT]: { count: 0, next: null, previous: null, results: [] },
    [ACCOUNT_RELATIONSHIPS_ENDPOINT]: [],
}

// Billing tab stories share the same account + notebooks mocks; they differ only in the insight and query responses.
function billingTabDecorators(
    insightsGet: Record<string, unknown>,
    queryPost: (info: MockResolverInfo) => Promise<[number, unknown] | undefined>
): ReturnType<typeof mswDecorator>[] {
    return [
        mswDecorator({
            get: {
                ...EXPANDED_ROW_FETCH_MOCKS,
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

const EXPANDED_ROW_DECORATORS_BASE = [
    mswDecorator({
        get: EXPANDED_ROW_FETCH_MOCKS,
    }),
]

// Expands the first row and asserts the expansion actually rendered. The click can race the table's
// render cycle and be swallowed, so verify and re-click instead of trusting a single click — a lost
// expansion then fails fast here, where Jest retries re-run the story cleanly, instead of burning
// the whole test budget inside the post-play waitForSelector.
async function expandFirstRow(canvasElement: HTMLElement): Promise<void> {
    const canvas = within(canvasElement)
    // Generous first wait: the whole scene mounts and the accounts query resolves before rows exist.
    await canvas.findByTitle('Show more', {}, { timeout: 15000 })
    for (let attempt = 0; attempt < 3; attempt++) {
        if (!canvasElement.querySelector('[data-attr="account-expansion"]')) {
            await userEvent.click(await canvas.findByTitle('Show more'))
        }
        try {
            await waitFor(
                () => {
                    if (!canvasElement.querySelector('[data-attr="account-expansion"]')) {
                        throw new Error('expansion not rendered yet')
                    }
                },
                { timeout: 3000 }
            )
            return
        } catch {
            // Expansion missing or collapsed again — loop around and re-click.
        }
    }
    throw new Error('Account row expansion did not render after 3 clicks')
}

// The snapshot fires well after `play` (page-ready waits, forced reflows, a dispatched resize),
// and the meta-level waitForSelector is satisfied by a collapsed table. Gating the snapshot on the
// expanded-row content turns a late-lost expansion into a retry instead of a flaky collapsed capture.
// play already asserts the expansion rendered, so keep this gate's timeout well under the Jest
// budget: a genuinely lost expansion should fail the attempt fast and retry cleanly, not burn the
// whole test timeout inside a Playwright wait.
const EXPANDED_ROW_TEST_OPTIONS = {
    waitForSelector: ['[data-attr="accounts-refresh"]', '[data-attr="account-expansion"]'],
    waitForSelectorTimeout: 15000,
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
                [RELATIONSHIP_DEFINITIONS_ENDPOINT]: RELATIONSHIP_DEFINITIONS,
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
        ...EXPANDED_ROW_DECORATORS_BASE,
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
        // Sidebar content verification is redundant for snapshot purposes since mock data is
        // deterministic — expanding (and verifying the expansion took) is all play needs to do.
        await expandFirstRow(canvasElement)
    },
}

export const RowExpandedWithNote: Story = {
    render: () => <App />,
    parameters: { testOptions: EXPANDED_ROW_TEST_OPTIONS },
    decorators: [
        ...EXPANDED_ROW_DECORATORS_BASE,
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
        await expandFirstRow(canvasElement)
    },
}

export const RowExpandedLinksDisabled: Story = {
    render: () => <App />,
    parameters: { testOptions: EXPANDED_ROW_TEST_OPTIONS },
    decorators: [
        ...EXPANDED_ROW_DECORATORS_BASE,
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
        await expandFirstRow(canvasElement)
    },
}

export const RowExpandedUsageNotFound: Story = {
    render: () => <App />,
    parameters: {
        testOptions: {
            ...EXPANDED_ROW_TEST_OPTIONS,
            waitForSelector: ['[data-attr="accounts-refresh"]', '[data-attr="account-billing-insight-not-found"]'],
        },
    },
    decorators: billingTabDecorators(EMPTY_INSIGHTS, mockAccountsQuery(SINGLE_ROW)),
    play: async ({ canvasElement }) => {
        await expandFirstRow(canvasElement)
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByRole('tab', { name: 'Usage' }, { timeout: 15000 }))
        await canvas.findByText('No billing usage insight here', {}, { timeout: 15000 })
    },
}
