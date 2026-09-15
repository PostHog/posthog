import { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { MockResolverInfo, Mocks } from '~/mocks/utils'

import type {
    CustomPropertyDefinitionApi,
    CustomPropertyValueApi,
    PaginatedAccountEmailThreadListApi,
    UserCustomerAnalyticsConfigApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { ACCOUNTS_DEFAULT_COLUMNS, customPropertyAlias } from './accountsColumnConfigLogic'

const QUERY_ENDPOINT = '/api/projects/:team_id/accounts_table_query/'
const ACCOUNT_RETRIEVE_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/'
const ACCOUNT_NOTEBOOKS_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/notebooks/'
const ACCOUNT_EMAIL_THREADS_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/email_threads/'
const ACCOUNT_EMAIL_THREAD_DETAIL_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/email_threads/:thread_id/'
const ACCOUNT_SUMMARIES_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/summaries/'
const ACCOUNT_SUPPORT_TICKETS_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/support_tickets/'
const ACCOUNT_RELATIONSHIPS_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/relationships/'
const ACCOUNT_PROPERTY_VALUES_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/custom_property_values/'
const ACCOUNT_SIDEBAR_CONFIG_ENDPOINT = 'api/projects/:team_id/user_customer_analytics_config/@me/'
const CUSTOM_PROPERTY_DEFINITIONS_ENDPOINT = 'api/projects/:team_id/custom_property_definitions/'
const FEATURE_REQUESTS_ENDPOINT = 'api/projects/:team_id/feature_requests/'
const RELATIONSHIP_DEFINITIONS_ENDPOINT = 'api/projects/:team_id/account_relationship_definitions/'
const ORGANIZATION_MEMBERS_ENDPOINT = 'api/projects/:team_id/organization_members/'
const WAREHOUSE_VIEW_LINK_ENDPOINT = 'api/environments/:team_id/warehouse_view_link/'
const ACCOUNT_ICON_ENDPOINT = 'api/projects/:team_id/accounts/icon/'
const INSIGHTS_ENDPOINT = 'api/environments/:team_id/insights/'

type AccountNameCell = { name: string; external_id: string | null; id: string; logo_domain: string | null }
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
        {
            id: '11111111-2222-3333-4444-555555555555',
            name: 'CSM',
            description: null,
            is_single_holder: true,
        },
        {
            id: '66666666-7777-8888-9999-aaaaaaaaaaaa',
            name: 'Account executive',
            description: null,
            is_single_holder: true,
        },
        {
            id: 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
            name: 'Account owner',
            description: null,
            is_single_holder: true,
        },
    ],
}

function buildAccountsTableQueryResponse(
    rows: AccountRow[],
    customProperties: Record<string, string> = {}
): Record<string, unknown> {
    return {
        kind: 'AccountsTableQuery',
        results: rows.map(([account, tags, noteCount, csm, accountExecutive, accountOwner]) => ({
            id: account.id,
            name: account.name,
            externalId: account.external_id,
            logoDomain: account.logo_domain,
            accountFields: { name: account.name },
            tags,
            noteCount,
            relationships: {
                '11111111-2222-3333-4444-555555555555': csm,
                '66666666-7777-8888-9999-aaaaaaaaaaaa': accountExecutive,
                'bbbbbbbb-cccc-dddd-eeee-ffffffffffff': accountOwner,
            },
            customProperties,
            customPropertyHistory: {},
        })),
        hasMore: false,
        limit: 100,
        offset: 0,
    }
}

const SAMPLE_ROWS: AccountRow[] = [
    [
        { name: 'Acme Inc', external_id: 'cust_acme_001', id: 'acc-1', logo_domain: 'acme.example' },
        ['enterprise', 'priority'],
        0,
        [178],
        [202],
        [],
    ],
    [{ name: 'Globex', external_id: 'cust_globex_002', id: 'acc-2', logo_domain: 'globex.example' }, [], 0, [], [], []],
    [{ name: 'Hooli', external_id: null, id: 'acc-3', logo_domain: null }, ['scaleup'], 0, [178], [], [202]],
]

const SINGLE_ROW: AccountRow[] = [
    [
        { name: 'Acme Inc', external_id: 'cust_acme_001', id: 'acc-1', logo_domain: 'acme.example' },
        ['enterprise', 'priority'],
        1,
        [178],
        [202],
        [],
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

const ACCOUNT_FEATURE_REQUEST = {
    id: '11111111-2222-3333-4444-555555555555',
    title: 'Scheduled account exports',
    description: 'Send account reports on a schedule.',
    request_status: 'requested',
    request_priority: null,
    is_archived: false,
    archived_at: null,
    archived_by: null,
    version: 1,
    account: { id: 'acc-1', name: 'Acme Inc' },
    account_links: [
        {
            id: '66666666-7777-8888-9999-aaaaaaaaaaaa',
            account: { id: 'acc-1', name: 'Acme Inc' },
            evidence: [],
            created_at: '2026-05-15T10:30:00Z',
            updated_at: '2026-05-15T10:30:00Z',
        },
    ],
    product_areas: [],
    created_by: 1,
    updated_by: 1,
    created_at: '2026-05-15T10:30:00Z',
    updated_at: '2026-05-15T10:30:00Z',
}

const EMPTY_INSIGHTS = { count: 0, next: null, previous: null, results: [] }
const EMPTY_EMAIL_THREADS: PaginatedAccountEmailThreadListApi = {
    count: 0,
    next: null,
    previous: null,
    results: [],
}

// Every fetch the expansion fires must be mocked (even if empty), because AccountNotebooksExpansion
// eagerly mounts the related-users, relationships, email-thread, and usage/spend billing logics up front. An
// unhandled fetch passes through msw to the static storybook server and errors out, and the failure
// re-render can collapse the expansion — making [data-attr="account-expansion"] disappear so the
// post-play waitForSelector times out. The related-users failure also pops an error toast, which the
// snapshot's loader wait can trip over.
const EXPANDED_ROW_FETCH_MOCKS = {
    [INSIGHTS_ENDPOINT]: EMPTY_INSIGHTS,
    [ORGANIZATION_MEMBERS_ENDPOINT]: { count: 0, next: null, previous: null, results: [] },
    [ACCOUNT_RELATIONSHIPS_ENDPOINT]: [],
    [ACCOUNT_EMAIL_THREADS_ENDPOINT]: EMPTY_EMAIL_THREADS,
    [ACCOUNT_SUMMARIES_ENDPOINT]: { count: 0, next: null, previous: null, results: [] },
    [ACCOUNT_SUPPORT_TICKETS_ENDPOINT]: [],
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

function expandedRowDecorators(
    emailThreads: PaginatedAccountEmailThreadListApi = EMPTY_EMAIL_THREADS
): ReturnType<typeof mswDecorator>[] {
    return [
        mswDecorator({
            get: {
                ...EXPANDED_ROW_FETCH_MOCKS,
                [ACCOUNT_EMAIL_THREADS_ENDPOINT]: emailThreads,
            },
        }),
    ]
}

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

function mockAccountsTableQuery(
    rows: AccountRow[],
    customProperties: Record<string, string> = {}
): (info: MockResolverInfo) => Promise<[number, unknown] | undefined> {
    return async ({ request }) => {
        const body = (await request.json()) as { query?: { kind?: string; metrics?: unknown[] } }
        const query = body?.query
        if (query?.kind === 'AccountsTableQuery') {
            return query.metrics
                ? [
                      200,
                      {
                          kind: 'AccountsTableQuery',
                          results: [],
                          hasMore: false,
                          limit: 100,
                          offset: 0,
                          metricsResults: [rows.length],
                      },
                  ]
                : [200, buildAccountsTableQueryResponse(rows, customProperties)]
        }
        return undefined
    }
}

// Storybook must not call logo.dev, and stable bytes keep visual snapshots deterministic.
const LOGO_SWATCHES: Record<string, string> = {
    'acme.example': '#8f68d4',
    'globex.example': '#dc9300',
}

function mockAccountIcon({ request }: MockResolverInfo): Response {
    const fill = LOGO_SWATCHES[new URL(request.url).searchParams.get('domain') ?? '']
    if (!fill) {
        return new Response(null, { status: 404 })
    }
    return new Response(
        `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" rx="4" fill="${fill}"/></svg>`,
        { headers: { 'Content-Type': 'image/svg+xml' } }
    )
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
                [ACCOUNT_ICON_ENDPOINT]: mockAccountIcon,
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
                [QUERY_ENDPOINT]: mockAccountsTableQuery(SAMPLE_ROWS),
            },
        }),
    ],
}

const ADDITIONAL_COLUMN_DEFINITIONS: CustomPropertyDefinitionApi[] = (
    [
        { name: 'Subscription cost', display_type: 'currency' },
        { name: 'Onboarding progress', display_type: 'percent' },
        { name: 'Seats', display_type: 'number' },
        { name: 'Deployment region', display_type: 'text' },
        { name: 'Plan', display_type: 'text' },
        { name: 'Account description', display_type: 'text' },
    ] satisfies Pick<CustomPropertyDefinitionApi, 'name' | 'display_type'>[]
).map((definition, index) => ({
    ...definition,
    id: `00000000-0000-0000-0000-00000000000${index}`,
    is_canonical: false,
    source: null,
    has_workflow_reference: false,
    created_at: '2026-05-01T00:00:00Z',
    created_by: null,
    updated_at: null,
    references: [],
}))

const ADDITIONAL_COLUMN_VALUES = Object.fromEntries(
    [
        '12345.67',
        '0.75',
        '250',
        'Europe',
        'Enterprise',
        'A long account description that needs more than one column width',
    ].map((value, index) => [ADDITIONAL_COLUMN_DEFINITIONS[index].id, value])
)

export const ManyColumns: Story = {
    render: () => <App />,
    parameters: {
        pageUrl: `${urls.customerAnalyticsAccounts()}#view=${encodeURIComponent(
            JSON.stringify({
                columns: [
                    ...ACCOUNTS_DEFAULT_COLUMNS,
                    'csm',
                    'external_id',
                    ...ADDITIONAL_COLUMN_DEFINITIONS.map(
                        ({ id }) => `accounts.custom_properties.values.\`${id}\` AS ${customPropertyAlias(id)}`
                    ),
                ],
            })
        )}`,
        testOptions: {
            waitForSelector: `[data-attr="accounts-table-sort-${customPropertyAlias(ADDITIONAL_COLUMN_DEFINITIONS[5].id)}"]`,
            viewport: { width: 1280, height: 960 },
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/column_configurations/': { count: 0, next: null, results: [] },
                'api/environments/:team_id/customer_journeys/': { count: 0, next: null, results: [] },
                'api/projects/:team_id/custom_property_definitions/': {
                    count: ADDITIONAL_COLUMN_DEFINITIONS.length,
                    next: null,
                    previous: null,
                    results: ADDITIONAL_COLUMN_DEFINITIONS,
                },
            },
            post: {
                [QUERY_ENDPOINT]: mockAccountsTableQuery(SAMPLE_ROWS, ADDITIONAL_COLUMN_VALUES),
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await within(canvasElement).findAllByText('Enterprise', {}, { timeout: 15000 })
        await waitFor(() => {
            const widths: number[] = []
            for (const definition of ADDITIONAL_COLUMN_DEFINITIONS) {
                const header = canvasElement
                    .querySelector(`[data-attr="accounts-table-sort-${customPropertyAlias(definition.id)}"]`)
                    ?.closest('th')
                const width = header?.getBoundingClientRect().width ?? 0
                if (width < 80 || width > 200) {
                    throw new Error('New account columns must size between 80px and 200px')
                }
                widths.push(width)
            }
            if (widths[4] <= widths[2] || widths.at(-1) !== 200) {
                throw new Error('Column sizes must account for values wider than the header and cap long content')
            }
            const expansionToggle = canvasElement.querySelector('.DataTable .LemonTable__toggle')
            if (!expansionToggle || expansionToggle.getBoundingClientRect().width === 0) {
                throw new Error('Automatic column widths must leave the row expansion control visible')
            }
            const scrollContainer = canvasElement.querySelector<HTMLElement>('.DataTable .ScrollableShadows__inner')
            if (!scrollContainer || scrollContainer.scrollWidth <= scrollContainer.clientWidth) {
                throw new Error('Account columns must scroll inside the table when they do not fit')
            }
            scrollContainer.scrollLeft = scrollContainer.scrollWidth
            if (scrollContainer.scrollLeft === 0) {
                throw new Error('The last account column must be reachable by scrolling')
            }
            scrollContainer.scrollLeft = 0
        })
    },
}

export const Empty: Story = {
    render: () => <App />,
    decorators: [
        mswDecorator({
            post: {
                [QUERY_ENDPOINT]: mockAccountsTableQuery([]),
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
                [QUERY_ENDPOINT]: mockAccountsTableQuery(SAMPLE_ROWS),
            },
        }),
    ],
}

const PINNED_PROPERTY_FIXTURES = [
    {
        id: 'summary',
        name: 'Account summary',
        display_type: 'text' as const,
        value: 'Evaluating the new dashboard with the customer success and implementation teams',
    },
    { id: 'active', name: 'Active', display_type: 'boolean' as const, value: false },
    { id: 'seats', name: 'Seats', display_type: 'number' as const, value: 42 },
    { id: 'unpinned', name: 'Unpinned property', display_type: 'text' as const, value: 'This value is not pinned' },
]
const PINNED_PROPERTY_DEFINITIONS: CustomPropertyDefinitionApi[] = PINNED_PROPERTY_FIXTURES.map(
    ({ id, name, display_type }) => ({
        id,
        name,
        display_type,
        target_type: 'account',
        is_canonical: false,
        source: null,
        references: [],
        has_workflow_reference: false,
        created_at: '2026-05-10T10:00:00Z',
        created_by: 1,
        updated_at: null,
    })
)
const PINNED_PROPERTY_VALUES: CustomPropertyValueApi[] = PINNED_PROPERTY_FIXTURES.map(({ id, value }) => ({
    id: `value-${id}`,
    definition_id: id,
    account_id: 'acc-1',
    value,
    created_at: '2026-05-10T10:00:00Z',
    created_by_id: 1,
}))
const PINNED_PROPERTIES_CONFIG: UserCustomerAnalyticsConfigApi = {
    pinned_properties: [
        { kind: 'custom_property', id: 'seats' },
        { kind: 'relationship', id: RELATIONSHIP_DEFINITIONS.results[0].id },
        { kind: 'custom_property', id: 'summary' },
        { kind: 'custom_property', id: 'active' },
    ],
}
const PINNED_EXPANSION_SELECTOR = '[data-attr="account-pinned-properties-expansion"]'
const PINNED_FIELD_SELECTOR = '[data-attr="account-property-row"]'
const PINNED_ROW_PARAMETERS = {
    featureFlags: [
        FEATURE_FLAGS.CUSTOMER_ANALYTICS,
        FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
        FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SCENE,
    ],
    testOptions: {
        waitForSelector: `${PINNED_EXPANSION_SELECTOR} ${PINNED_FIELD_SELECTOR}`,
        viewport: { width: 1440, height: 900 },
    },
}

function pinnedRowDecorators(overrides: Mocks['get'] = {}): ReturnType<typeof mswDecorator>[] {
    return [
        mswDecorator({
            get: {
                'api/projects/:team_id/column_configurations/': { count: 0, next: null, previous: null, results: [] },
                'api/environments/:team_id/customer_journeys/': { count: 0, next: null, previous: null, results: [] },
                [ACCOUNT_SIDEBAR_CONFIG_ENDPOINT]: PINNED_PROPERTIES_CONFIG,
                [CUSTOM_PROPERTY_DEFINITIONS_ENDPOINT]: {
                    count: PINNED_PROPERTY_DEFINITIONS.length,
                    next: null,
                    previous: null,
                    results: PINNED_PROPERTY_DEFINITIONS,
                },
                [ACCOUNT_PROPERTY_VALUES_ENDPOINT]: PINNED_PROPERTY_VALUES,
                [ACCOUNT_RELATIONSHIPS_ENDPOINT]: [
                    {
                        id: 'assignment-csm',
                        definition: RELATIONSHIP_DEFINITIONS.results[0],
                        user: { id: 178, email: 'alex@example.com' },
                        started_at: '2026-05-10T10:00:00Z',
                        ended_at: null,
                    },
                ],
                ...overrides,
            },
            post: {
                [QUERY_ENDPOINT]: mockAccountsTableQuery(SINGLE_ROW),
            },
        }),
    ]
}

async function expandPinnedRow(canvasElement: HTMLElement): Promise<HTMLElement> {
    const canvas = within(canvasElement)
    await canvas.findByText('Acme Inc', {}, { timeout: 15000 })
    await userEvent.click(await canvas.findByTitle('Show more'))
    return await waitFor(() => {
        const expansion = canvasElement.querySelector<HTMLElement>(PINNED_EXPANSION_SELECTOR)
        if (!expansion) {
            throw new Error('Pinned properties did not expand')
        }
        if (
            canvasElement.querySelector('[data-attr="account-expansion"]') ||
            within(expansion).queryByRole('tablist')
        ) {
            throw new Error('Pinned expansion must not render account detail tabs')
        }
        return expansion
    })
}

async function assertPinnedValues(expansion: HTMLElement): Promise<void> {
    const expected = [
        ['Seats', '42'],
        ['CSM', 'alex@example.com'],
        ['Account summary', 'Evaluating the new dashboard with the customer success and implementation teams'],
        ['Active', 'No'],
    ]
    await waitFor(() => {
        const fields = expansion.querySelectorAll<HTMLElement>(PINNED_FIELD_SELECTOR)
        if (fields.length !== expected.length) {
            throw new Error('Expansion must show only pinned properties')
        }
        for (const [index, [label, value]] of expected.entries()) {
            const field = within(fields[index])
            field.getByText(label)
            field.getByText(value)
        }
    })
    if (
        within(expansion).queryByText('Unpinned property') ||
        within(expansion).queryByText('This value is not pinned')
    ) {
        throw new Error('Pinned properties must exclude unpinned content')
    }
}

export const RowExpandedPinnedProperties: Story = {
    render: () => <App />,
    parameters: PINNED_ROW_PARAMETERS,
    decorators: pinnedRowDecorators(),
    play: async ({ canvasElement }) => {
        await assertPinnedValues(await expandPinnedRow(canvasElement))
        await userEvent.click(within(canvasElement).getByTitle('Show less'))
        await waitFor(() => {
            if (canvasElement.querySelector(PINNED_EXPANSION_SELECTOR)) {
                throw new Error('Pinned properties did not collapse')
            }
        })
        await assertPinnedValues(await expandPinnedRow(canvasElement))
    },
}

export const RowExpandedPinnedPropertiesNarrow: Story = {
    ...RowExpandedPinnedProperties,
    parameters: {
        ...PINNED_ROW_PARAMETERS,
        pageUrl: `${urls.customerAnalyticsAccounts()}#view=${encodeURIComponent(JSON.stringify({ columns: ['name'] }))}`,
        testOptions: {
            ...PINNED_ROW_PARAMETERS.testOptions,
            viewport: { width: 800, height: 900 },
        },
    },
    play: async ({ canvasElement }) => {
        await assertPinnedValues(await expandPinnedRow(canvasElement))
    },
}

export const RowExpandedNoPinnedProperties: Story = {
    render: () => <App />,
    parameters: {
        ...PINNED_ROW_PARAMETERS,
        testOptions: {
            waitForSelector: `${PINNED_EXPANSION_SELECTOR} [data-attr="account-pin-properties-empty"]`,
        },
    },
    decorators: pinnedRowDecorators({ [ACCOUNT_SIDEBAR_CONFIG_ENDPOINT]: { pinned_properties: [] } }),
    play: async ({ canvasElement }) => {
        const expansion = await expandPinnedRow(canvasElement)
        await within(expansion).findByRole('button', { name: 'Pin properties' })
        within(expansion).getByText('Pin the account details you use most.')
        within(expansion).getByText('Properties')
        if (
            within(expansion).queryByLabelText('Configure pinned properties') ||
            within(expansion).queryByRole('link')
        ) {
            throw new Error('Empty expansion must offer the Pin properties button without a gear or link')
        }
        if (expansion.querySelector(PINNED_FIELD_SELECTOR)) {
            throw new Error('Empty expansion must not show unpinned properties')
        }
    },
}

export const RowExpandedPinnedPropertiesError: Story = {
    render: () => <App />,
    parameters: {
        ...PINNED_ROW_PARAMETERS,
        testOptions: { waitForSelector: `${PINNED_EXPANSION_SELECTOR} button` },
    },
    decorators: pinnedRowDecorators({
        [ACCOUNT_PROPERTY_VALUES_ENDPOINT]: [500, { detail: 'Could not load pinned properties.' }],
    }),
    play: async ({ canvasElement }) => {
        const expansion = await expandPinnedRow(canvasElement)
        await within(expansion).findByText('Could not load pinned properties.')
        await within(expansion).findAllByRole('button', { name: 'Try again' })
        if (
            expansion.querySelector('[data-attr="account-pin-properties-empty"]') ||
            expansion.querySelector(PINNED_FIELD_SELECTOR)
        ) {
            throw new Error('A failed property request must not render empty or partial values')
        }
    },
}

export const RowExpandedEmpty: Story = {
    render: () => <App />,
    parameters: { testOptions: EXPANDED_ROW_TEST_OPTIONS },
    decorators: [
        ...expandedRowDecorators(),
        mswDecorator({
            get: {
                [ACCOUNT_RETRIEVE_ENDPOINT]: ACCOUNT_WITH_LINKS,
                [ACCOUNT_NOTEBOOKS_ENDPOINT]: { count: 0, next: null, previous: null, results: [] },
            },
            post: {
                [QUERY_ENDPOINT]: mockAccountsTableQuery(SINGLE_ROW),
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
        ...expandedRowDecorators(),
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
                [QUERY_ENDPOINT]: mockAccountsTableQuery(SINGLE_ROW),
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await expandFirstRow(canvasElement)
    },
}

export const RowExpandedFeatureRequests: Story = {
    render: () => <App />,
    parameters: {
        featureFlags: [
            FEATURE_FLAGS.CUSTOMER_ANALYTICS,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS,
        ],
        testOptions: {
            ...EXPANDED_ROW_TEST_OPTIONS,
            waitForSelector: ['[data-attr="accounts-refresh"]', '[data-attr="account-feature-requests"]'],
        },
    },
    decorators: [
        ...expandedRowDecorators(),
        mswDecorator({
            get: {
                [ACCOUNT_RETRIEVE_ENDPOINT]: ACCOUNT_WITH_LINKS,
                [ACCOUNT_NOTEBOOKS_ENDPOINT]: { count: 0, next: null, previous: null, results: [] },
                [FEATURE_REQUESTS_ENDPOINT]: {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [ACCOUNT_FEATURE_REQUEST],
                },
            },
            post: {
                [QUERY_ENDPOINT]: mockAccountsTableQuery(SINGLE_ROW),
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await expandFirstRow(canvasElement)
        const expansion = canvasElement.querySelector('[data-attr="account-expansion"]') as HTMLElement
        await userEvent.click(await within(expansion).findByText('Feature requests', {}, { timeout: 15000 }))
        await waitFor(() => {
            if (!canvasElement.querySelector('[data-attr="account-feature-requests"]')) {
                throw new Error('Feature requests tab did not render')
            }
        })
    },
}

export const RowExpandedConversations: Story = {
    render: () => <App />,
    parameters: {
        testOptions: {
            ...EXPANDED_ROW_TEST_OPTIONS,
            waitForSelector: ['[data-attr="accounts-refresh"]', '[data-attr="account-email-thread-detail"]'],
        },
    },
    decorators: [
        ...expandedRowDecorators({
            count: 1,
            next: null,
            previous: null,
            results: [
                {
                    id: '11111111-1111-1111-1111-111111111111',
                    subject: 'Renewal planning',
                    preview: 'I shared the revised timeline with the team.',
                    first_message_at: '2026-05-20T09:00:00Z',
                    first_message: {
                        sender: {
                            name: 'Example buyer',
                            email: 'buyer@example.com',
                            person_id: null,
                            distinct_id: null,
                        },
                        sent_at: '2026-05-20T09:00:00Z',
                        direction: 'inbound',
                    },
                    last_message_at: '2026-05-20T11:30:00Z',
                    last_message: {
                        sender: {
                            name: 'Alice Anderson',
                            email: 'alice@posthog.com',
                            person_id: null,
                            distinct_id: null,
                        },
                        sent_at: '2026-05-20T11:30:00Z',
                        direction: 'outbound',
                    },
                    message_count: 2,
                    participants: [
                        {
                            email: 'buyer@example.com',
                            display_name: 'Example buyer',
                            kind: 'customer',
                            person_id: null,
                        },
                    ],
                },
            ],
        }),
        mswDecorator({
            get: {
                [ACCOUNT_RETRIEVE_ENDPOINT]: ACCOUNT_WITH_LINKS,
                [ACCOUNT_NOTEBOOKS_ENDPOINT]: { count: 0, next: null, previous: null, results: [] },
                [ACCOUNT_EMAIL_THREAD_DETAIL_ENDPOINT]: {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: '22222222-2222-2222-2222-222222222222',
                            sent_at: '2026-05-20T09:00:00Z',
                            sender: { name: 'Example buyer', email: 'buyer@example.com' },
                            to_recipients: [{ name: 'Alice Anderson', email: 'alice@posthog.com' }],
                            cc_recipients: [],
                            sender_authenticated: false,
                            direction: 'inbound',
                            content: 'Could you send the updated renewal timeline?',
                        },
                        {
                            id: '33333333-3333-3333-3333-333333333333',
                            sent_at: '2026-05-20T11:30:00Z',
                            sender: { name: 'Alice Anderson', email: 'alice@posthog.com' },
                            to_recipients: [{ name: 'Example buyer', email: 'buyer@example.com' }],
                            cc_recipients: [],
                            sender_authenticated: true,
                            direction: 'outbound',
                            content: 'I shared the revised timeline with the team.',
                        },
                    ],
                },
            },
            post: {
                [QUERY_ENDPOINT]: mockAccountsTableQuery(SINGLE_ROW),
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await expandFirstRow(canvasElement)
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByRole('tab', { name: 'Conversations' }, { timeout: 15000 }))
        await waitFor(
            () => {
                if (!canvasElement.querySelector('[data-attr="account-conversations-table"]')) {
                    throw new Error('Conversations table did not render')
                }
            },
            { timeout: 15000 }
        )
        const table = canvasElement.querySelector('[data-attr="account-conversations-table"]') as HTMLElement
        if (within(table).queryByTitle('Show more')) {
            throw new Error('Conversation expansion toggle should not render')
        }
        await userEvent.click(await within(table).findByText('Renewal planning'))
        await waitFor(() => {
            if (!canvasElement.querySelector('[data-attr="account-email-thread-detail"]')) {
                throw new Error('Email thread detail did not render')
            }
        })
        await userEvent.click(await within(table).findByText('Renewal planning'))
        await waitFor(() => {
            if (canvasElement.querySelector('[data-attr="account-email-thread-detail"]')) {
                throw new Error('Email thread detail did not collapse')
            }
        })
        await userEvent.click(await within(table).findByText('Renewal planning'))
        await waitFor(() => {
            if (!canvasElement.querySelector('[data-attr="account-email-thread-detail"]')) {
                throw new Error('Email thread detail did not reopen')
            }
        })
    },
}

export const RowExpandedLinksDisabled: Story = {
    render: () => <App />,
    parameters: { testOptions: EXPANDED_ROW_TEST_OPTIONS },
    decorators: [
        ...expandedRowDecorators(),
        mswDecorator({
            get: {
                [ACCOUNT_RETRIEVE_ENDPOINT]: ACCOUNT_WITHOUT_LINKS,
                [ACCOUNT_NOTEBOOKS_ENDPOINT]: { count: 0, next: null, previous: null, results: [] },
            },
            post: {
                [QUERY_ENDPOINT]: mockAccountsTableQuery(SINGLE_ROW),
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
    decorators: billingTabDecorators(EMPTY_INSIGHTS, mockAccountsTableQuery(SINGLE_ROW)),
    play: async ({ canvasElement }) => {
        await expandFirstRow(canvasElement)
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByRole('tab', { name: 'Usage' }, { timeout: 15000 }))
        await canvas.findByText('No billing usage insight here', {}, { timeout: 15000 })
    },
}
