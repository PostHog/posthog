import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const QUERY_ENDPOINT = '/api/environments/:team_id/query/:kind/'
const ACCOUNT_RETRIEVE_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/'
const ACCOUNT_NOTEBOOKS_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/notebooks/'
const WAREHOUSE_VIEW_LINK_ENDPOINT = 'api/environments/:team_id/warehouse_view_link/'

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

function mockAccountsQuery(rows: AccountRow[]): (req: { body: unknown }) => [number, unknown] | undefined {
    return (req) => {
        const kind = (req.body as { query?: { kind?: string } })?.query?.kind
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
    decorators: [
        mswDecorator({
            get: {
                [WAREHOUSE_VIEW_LINK_ENDPOINT]: { count: 0, next: null, previous: null, results: [] },
            },
            post: {
                [QUERY_ENDPOINT]: mockAccountsQuery(SAMPLE_ROWS),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    render: () => <App />,
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
}

export const RowExpandedEmpty: Story = {
    render: () => <App />,
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
