import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { ExternalDataSourceType, SourceConfig } from '~/queries/schema/schema-general'

import { ContextWarehouseStep } from './ContextWarehouseStep'

// The catalog endpoint (`external_data_sources/wizard`) returns the source picker contents.
// Stripe carries a flat secret-key field so the inline wizard renders a visible form input when
// selected — the real Stripe config nests auth behind a select + OAuth option, which would pull in
// integration calls we don't need to demonstrate the connect form.
const AVAILABLE_SOURCES: Record<string, SourceConfig> = {
    Stripe: {
        name: 'Stripe' as ExternalDataSourceType,
        label: 'Stripe',
        iconPath: '/static/services/stripe.png',
        caption: 'Connect your Stripe account to sync revenue, subscriptions, and invoices into PostHog.',
        featured: true,
        fields: [
            {
                name: 'stripe_secret_key',
                label: 'API key',
                type: 'password',
                required: true,
                placeholder: 'rk_live_...',
                secret: true,
            },
        ],
    },
    Hubspot: {
        name: 'Hubspot' as ExternalDataSourceType,
        label: 'HubSpot',
        iconPath: '/static/services/hubspot.png',
        caption: '',
        featured: true,
        fields: [],
    },
    Postgres: {
        name: 'Postgres' as ExternalDataSourceType,
        label: 'PostgreSQL',
        iconPath: '/static/services/postgres.png',
        caption: '',
        featured: true,
        fields: [],
    },
    Zendesk: {
        name: 'Zendesk' as ExternalDataSourceType,
        label: 'Zendesk',
        iconPath: '/static/services/zendesk.png',
        caption: '',
        featured: true,
        fields: [],
    },
    // Non-featured sources sit behind the "Show N more" toggle.
    Salesforce: {
        name: 'Salesforce' as ExternalDataSourceType,
        label: 'Salesforce',
        iconPath: '/static/services/salesforce.png',
        caption: '',
        featured: false,
        fields: [],
    },
    Snowflake: {
        name: 'Snowflake' as ExternalDataSourceType,
        label: 'Snowflake',
        iconPath: '/static/services/snowflake.png',
        caption: '',
        featured: false,
        fields: [],
    },
    Chargebee: {
        name: 'Chargebee' as ExternalDataSourceType,
        label: 'Chargebee',
        iconPath: '/static/services/chargebee.png',
        caption: '',
        featured: false,
        fields: [],
    },
}

// One already-connected source so the green "Connected" row renders. The `connectors` selector flags
// a catalog source as connected when this list holds a matching `source_type`.
const CONNECTED_STRIPE_SOURCE = {
    id: 'stripe-source-id',
    source_type: 'Stripe',
    prefix: '',
    status: 'Completed',
    schemas: [],
    created_at: '2026-06-01T00:00:00Z',
}

// Wrap the step in a card that mirrors the real onboarding surface so the body reads like the
// actual scene rather than a bare component.
function OnboardingCard({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="min-h-screen bg-primary p-8">
            <div className="max-w-xl mx-auto bg-surface-primary border border-primary rounded-xl p-8">
                <h2 className="text-xl font-semibold mb-4">Connect your data</h2>
                {children}
            </div>
        </div>
    )
}

const meta: Meta<typeof ContextWarehouseStep> = {
    title: 'Scenes-Other/Onboarding/Self-Driving/Connect data',
    component: ContextWarehouseStep,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-26',
    },
    decorators: [
        (Story) => (
            <OnboardingCard>
                <Story />
            </OnboardingCard>
        ),
        mswDecorator({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard': () => [200, AVAILABLE_SOURCES],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof ContextWarehouseStep>

// Picker — the default view: featured sources listed with a "Show more" toggle below.
export const Picker: Story = {}

// Searching — typing filters the list to the single matching source.
export const Searching: Story = {
    play: async ({ canvasElement }) => {
        const searchInput = await waitFor(() => {
            const input = canvasElement.querySelector<HTMLInputElement>('input[type="search"]')
            if (!input) {
                throw new Error('Search input not rendered')
            }
            return input
        })

        await userEvent.type(searchInput, 'stripe')

        // Only Stripe should remain, and the other featured sources should be filtered out.
        await waitFor(() => {
            if (!canvasElement.textContent?.includes('Stripe')) {
                throw new Error('Filtered source not visible')
            }
            if (canvasElement.textContent?.includes('PostgreSQL')) {
                throw new Error('Non-matching source still visible')
            }
        })
    },
}

// SearchingEmpty — a query that matches nothing surfaces the empty state.
export const SearchingEmpty: Story = {
    play: async ({ canvasElement }) => {
        const searchInput = await waitFor(() => {
            const input = canvasElement.querySelector<HTMLInputElement>('input[type="search"]')
            if (!input) {
                throw new Error('Search input not rendered')
            }
            return input
        })

        await userEvent.type(searchInput, 'nonexistent source')

        await waitFor(() => {
            if (!canvasElement.textContent?.includes('No sources match')) {
                throw new Error('Empty state not visible')
            }
        })
    },
}

// Connecting — clicking a source row swaps the picker for the inline source wizard, pre-selected to
// Stripe and showing its connection form (the "API key" field).
export const Connecting: Story = {
    play: async ({ canvasElement }) => {
        const stripeRow = await waitFor(() => {
            const row = Array.from(canvasElement.querySelectorAll<HTMLButtonElement>('button')).find((button) =>
                button.textContent?.includes('Stripe')
            )
            if (!row) {
                throw new Error('Stripe source row not rendered')
            }
            return row
        })

        await userEvent.click(stripeRow)

        // The inline wizard's step-2 form should render the Stripe secret-key input.
        await waitFor(() => {
            if (!canvasElement.querySelector('[data-attr="stripe_secret_key"]')) {
                throw new Error('Wizard connection form not rendered')
            }
        })
    },
}

// WithConnectedSource — one source already connected shows as a green "Connected" row above the
// remaining picker.
export const WithConnectedSource: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/external_data_sources/': () => [
                        200,
                        toPaginatedResponse([CONNECTED_STRIPE_SOURCE]),
                    ],
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        await waitFor(() => {
            if (!canvasElement.textContent?.includes('Connected')) {
                throw new Error('Connected row not rendered')
            }
        })
    },
}

// Loading — the catalog request never resolves, so the skeleton placeholder stays on screen.
export const Loading: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/external_data_sources/wizard': () => new Promise(() => {}),
                },
            },
        },
    },
}
