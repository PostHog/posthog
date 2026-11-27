import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { userEvent } from 'storybook/test'

import { ServiceAccountDetails } from './ServiceAccountDetails'
import { ServiceAccountsTable } from './ServiceAccountsTable'

const account = {
    id: '11111111-1111-4111-8111-111111111111',
    name: 'Build runner',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
}
const meta: Meta<typeof ServiceAccountsTable> = {
    title: 'Scenes-Other/Settings/Organization/Service accounts',
    component: ServiceAccountsTable,
    args: { organizationId: 'test-organization' },
    parameters: {
        mockDate: '2026-01-10',
        pageUrl: '/settings/organization-members#service-accounts',
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/:organization_id/service_accounts/': { results: [account], next: null },
                '/api/organizations/:organization_id/service_accounts/:id/': account,
                '/api/organizations/:organization_id/service_accounts/:id/api_keys/': [
                    {
                        id: 'example-key',
                        label: 'Build reports',
                        mask_value: 'phx_...demo',
                        scopes: ['insight:read'],
                        scoped_teams: null,
                        scoped_organizations: null,
                        created_at: '2026-01-02T00:00:00Z',
                        last_used_at: null,
                        expires_at: null,
                    },
                ],
            },
            post: { '/api/organizations/:organization_id/service_accounts/': [201, account] },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof ServiceAccountsTable>

export const List: Story = {}
export const Details: Story = {
    render: ({ organizationId }) => <ServiceAccountDetails organizationId={organizationId} accountId={account.id} />,
}
export const Create: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Create service account'))
    },
}
export const QuillList: Story = { parameters: { featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV] } }
export const QuillDetails: Story = {
    ...Details,
    parameters: { ...Details.parameters, featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV] },
}
export const QuillCreate: Story = { ...Create, parameters: { featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV] } }
export const Empty: Story = {
    decorators: [
        mswDecorator({ get: { '/api/organizations/:organization_id/service_accounts/': { results: [], next: null } } }),
    ],
}
export const LoadError: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/organizations/:organization_id/service_accounts/': [500, { detail: 'Unavailable' }] },
        }),
    ],
}
