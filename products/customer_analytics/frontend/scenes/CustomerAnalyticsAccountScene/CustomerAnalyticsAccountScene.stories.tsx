import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { CustomPropertyValueWriteApi, AccountRelationshipWriteApi } from '../../generated/api.schemas'

const ACCOUNT_ID = '11111111-2222-4333-8444-555555555555'
const ACCOUNT_RETRIEVE_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/'
const ACCOUNT_NOTEBOOKS_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/notebooks/'
const ACCOUNT_ICON_ENDPOINT = 'api/projects/:team_id/accounts/icon/'
const VALUES_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/custom_property_values/'
const ASSIGNMENTS_ENDPOINT = 'api/projects/:team_id/accounts/:account_id/relationships/'
const ACCOUNT_SIDEBAR_CONFIG_ENDPOINT = 'api/projects/:team_id/user_customer_analytics_config/@me/'
const CUSTOM_PROPERTY_DEFINITIONS_ENDPOINT = 'api/projects/:team_id/custom_property_definitions/'
const RELATIONSHIP_DEFINITIONS_ENDPOINT = 'api/projects/:team_id/account_relationship_definitions/'

const account = {
    id: ACCOUNT_ID,
    name: 'Example Labs',
    external_id: 'example_labs_42',
    properties: {
        website_domain: 'example.com',
        email_domains: ['example.com'],
        known_emails: [],
    },
    tags: ['enterprise', 'onboarding'],
    notebooks: ['note1234'],
    slack_summary_cadence: null,
    churned_at: null,
    ignored_at: null,
    created_at: '2026-05-10T10:00:00Z',
    created_by: null,
    updated_at: '2026-05-20T14:30:00Z',
}

const notebooks = {
    count: 1,
    next: null,
    previous: null,
    results: [
        {
            id: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
            short_id: 'note1234',
            title: 'Implementation planning',
            content: null,
            text_content: 'The team plans to finish its data import and review the first dashboard next week.',
            created_at: '2026-05-18T09:15:00Z',
            created_by: {
                id: 7,
                uuid: '99999999-8888-4777-8666-555555555555',
                email: 'alex@example.com',
                first_name: 'Alex',
                last_name: 'River',
                is_email_verified: true,
            },
            last_modified_at: '2026-05-18T09:15:00Z',
            last_modified_by: null,
        },
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Customer Analytics/Account detail',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-05-21',
        featureFlags: [
            FEATURE_FLAGS.CUSTOMER_ANALYTICS,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SCENE,
        ],
        pageUrl: urls.customerAnalyticsAccount(ACCOUNT_ID),
        testOptions: {
            waitForSelector: ['[data-attr="customer-analytics-account-scene"]', '[data-attr="account-notes"]'],
            viewport: { width: 1280, height: 900 },
        },
    },
    decorators: [
        mswDecorator({
            get: {
                [ACCOUNT_RETRIEVE_ENDPOINT]: account,
                [ACCOUNT_NOTEBOOKS_ENDPOINT]: notebooks,
                [ACCOUNT_ICON_ENDPOINT]: () =>
                    new Response(
                        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" rx="4" fill="#8f68d4"/></svg>',
                        { headers: { 'Content-Type': 'image/svg+xml' } }
                    ),
                [ACCOUNT_SIDEBAR_CONFIG_ENDPOINT]: { pinned_properties: [] },
                [VALUES_ENDPOINT]: [],
                [ASSIGNMENTS_ENDPOINT]: [],
                [CUSTOM_PROPERTY_DEFINITIONS_ENDPOINT]: {
                    count: 1,
                    results: [
                        {
                            id: '22222222-3333-4444-8555-666666666666',
                            name: 'Annual recurring revenue',
                            description: null,
                            display_type: 'currency',
                            target_type: 'account',
                            is_big_number: false,
                            is_canonical: false,
                            options: null,
                            source: null,
                            created_at: '2026-05-10T10:00:00Z',
                            created_by: 1,
                            updated_at: '2026-05-20T14:30:00Z',
                            references: [],
                            has_workflow_reference: false,
                        },
                    ],
                },
                [RELATIONSHIP_DEFINITIONS_ENDPOINT]: {
                    count: 1,
                    results: [
                        {
                            id: '33333333-4444-4555-8666-777777777777',
                            name: 'Customer success manager',
                            description: null,
                            is_single_holder: true,
                        },
                    ],
                },
            },
            patch: {
                [ACCOUNT_SIDEBAR_CONFIG_ENDPOINT]: async ({ request }) => [200, await request.json()],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    render: () => <App />,
}

export const Narrow: Story = {
    render: () => <App />,
    parameters: {
        testOptions: {
            waitForSelector: '[data-attr="customer-analytics-account-scene"]',
            viewport: { width: 800, height: 900 },
        },
    },
}

const pinnedDefinitions = [
    ['summary', 'Account summary', 'text', 'Evaluating the new dashboard'],
    ['website', 'Success plan', 'link', 'https://example.com/plan'],
    ['seats', 'Seats', 'number', 42],
    ['arr', 'Annual recurring revenue', 'currency', 125000],
    ['growth', 'Monthly growth', 'percent', 0.15],
    ['renewal', 'Renewal date', 'date', '2026-11-14'],
    ['check-in', 'Next check-in', 'datetime', '2026-11-14T10:30:00Z'],
    ['active', 'Active', 'boolean', false],
    ['segment', 'Segment', 'select', 'Growth'],
    ['canonical', 'Last Slack message', 'datetime', '2026-05-20T10:00:00Z'],
].map(([id, name, display_type, value]) => ({
    definition: {
        id,
        name,
        display_type,
        target_type: 'account',
        is_canonical: id === 'canonical',
        has_workflow_reference: id === 'active',
        source: null,
        references: [],
        options:
            id === 'segment'
                ? [
                      { id: 'growth', label: 'Growth', color: 'preset-1' },
                      { id: 'enterprise', label: 'Enterprise', color: 'preset-2' },
                  ]
                : null,
        created_at: '2026-05-10T10:00:00Z',
        created_by: 1,
        updated_at: null,
    },
    value: {
        id: `value-${id}`,
        definition_id: id,
        account_id: ACCOUNT_ID,
        value,
        created_at: '2026-05-10T10:00:00Z',
        created_by_id: 1,
    },
}))
const pinnedRelationships = [
    { id: 'csm', name: 'Customer success manager', is_single_holder: true },
    { id: 'team', name: 'Account team', is_single_holder: false },
]
const pinnedMembers = [
    {
        id: 1,
        email: 'alex@example.com',
        first_name: 'Alex',
        last_name: 'River',
        uuid: '11111111-1111-4111-8111-111111111111',
    },
    {
        id: 2,
        email: 'jordan@example.com',
        first_name: 'Jordan',
        last_name: 'Bell',
        uuid: '22222222-2222-4222-8222-222222222222',
    },
]
const pinnedValues = new Map(pinnedDefinitions.map(({ definition, value }) => [definition.id, value]))
let pinnedAssignments = pinnedRelationships.map((definition) => ({
    id: `assignment-${definition.id}`,
    definition,
    user: pinnedMembers[0],
    started_at: '2026-05-10T10:00:00Z',
    ended_at: null as string | null,
}))
const pinnedDecorator = mswDecorator({
    get: {
        [ACCOUNT_SIDEBAR_CONFIG_ENDPOINT]: {
            pinned_properties: [
                ...pinnedDefinitions.map(({ definition }) => ({ kind: 'custom_property', id: definition.id })),
                ...pinnedRelationships.map(({ id }) => ({ kind: 'relationship', id })),
            ],
        },
        [CUSTOM_PROPERTY_DEFINITIONS_ENDPOINT]: {
            count: pinnedDefinitions.length,
            results: pinnedDefinitions.map(({ definition }) => definition),
        },
        [RELATIONSHIP_DEFINITIONS_ENDPOINT]: { count: pinnedRelationships.length, results: pinnedRelationships },
        [VALUES_ENDPOINT]: () => [...pinnedValues.values()],
        [ASSIGNMENTS_ENDPOINT]: () => pinnedAssignments,
        'api/organizations/:organization_id/members/': {
            count: pinnedMembers.length,
            results: pinnedMembers.map((user) => ({ id: user.uuid, user, level: 1 })),
        },
    },
    post: {
        [VALUES_ENDPOINT]: async ({ request }) => {
            const { definition, value } = (await request.json()) as CustomPropertyValueWriteApi
            if (value === null) {
                pinnedValues.delete(definition)
                return [204, null]
            }
            const row = {
                id: `value-${definition}`,
                definition_id: definition,
                account_id: ACCOUNT_ID,
                value,
                created_at: '2026-05-21T10:00:00Z',
                created_by_id: 1,
            }
            pinnedValues.set(definition, row)
            return [201, row]
        },
        [ASSIGNMENTS_ENDPOINT]: async ({ request }) => {
            const { definition: definitionId, user: userId } = (await request.json()) as AccountRelationshipWriteApi
            const definition = pinnedRelationships.find(({ id }) => id === definitionId)!
            if (definition.is_single_holder) {
                pinnedAssignments = pinnedAssignments.map((row) =>
                    row.definition.id === definitionId ? { ...row, ended_at: '2026-05-21T10:00:00Z' } : row
                )
            }
            const row = {
                id: `assignment-${definitionId}-${userId}`,
                definition,
                user: pinnedMembers.find(({ id }) => id === userId)!,
                started_at: '2026-05-21T10:00:00Z',
                ended_at: null,
            }
            pinnedAssignments.push(row)
            return [201, row]
        },
        'api/projects/:team_id/accounts/:account_id/relationships/:id/end/': ({ params }) => {
            const row = pinnedAssignments.find(({ id }) => id === params.id)!
            row.ended_at = '2026-05-21T10:00:00Z'
            return [200, row]
        },
    },
})

export const PinnedProperties: Story = {
    render: () => <App />,
    beforeEach: () => {
        pinnedValues.clear()
        for (const { definition, value } of pinnedDefinitions) {
            pinnedValues.set(definition.id, value)
        }
        pinnedAssignments = pinnedRelationships.map((definition) => ({
            id: `assignment-${definition.id}`,
            definition,
            user: pinnedMembers[0],
            started_at: '2026-05-10T10:00:00Z',
            ended_at: null,
        }))
    },
    decorators: [pinnedDecorator],
    parameters: {
        testOptions: { waitForSelector: '[data-attr="account-property-row"]', viewport: { width: 1440, height: 900 } },
    },
}

export const PinnedPropertiesNarrow: Story = {
    ...PinnedProperties,
    parameters: {
        testOptions: { waitForSelector: '[data-attr="account-property-row"]', viewport: { width: 800, height: 900 } },
    },
}
