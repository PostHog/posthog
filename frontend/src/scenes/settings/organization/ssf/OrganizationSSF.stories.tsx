import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { OrganizationMembershipLevel } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { SSFStreamStatusEnumApi } from '~/generated/core/api.schemas'
import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import { AvailableFeature } from '~/types'

import { OrganizationSSF } from './OrganizationSSF'
import {
    SSF_INCOMING_CONNECTION,
    SSF_INCOMING_STREAM,
    SSF_OUTGOING_CONNECTION,
    SSF_OUTGOING_STREAM,
    SSF_SETTINGS,
} from './ssfSettingsFixtures'

const user = {
    ...MOCK_DEFAULT_USER,
    organization: {
        ...MOCK_DEFAULT_ORGANIZATION,
        membership_level: OrganizationMembershipLevel.Admin,
        available_product_features: [{ key: AvailableFeature.SSF, name: 'Shared Signals Framework' }],
    },
}

const configured = {
    get: {
        '/api/organizations/:id/ssf': SSF_SETTINGS,
        '/api/organizations/:id/ssf/connections': [SSF_INCOMING_CONNECTION, SSF_OUTGOING_CONNECTION],
        '/api/organizations/:id/ssf/streams': [
            { ...SSF_INCOMING_STREAM, last_verified_at: '2026-10-23T11:55:00Z' },
            {
                ...SSF_INCOMING_STREAM,
                id: '01980000-0000-4000-8000-000000000013',
                description: 'Device security events',
                remote_stream_id: 'upstream-stream-two',
                endpoint_url:
                    'https://posthog.example.com/ssf/example-organization/events/01980000-0000-4000-8000-000000000013',
            },
            SSF_OUTGOING_STREAM,
        ],
    },
}

const meta: Meta<typeof OrganizationSSF> = {
    title: 'Scenes-App/Settings/Shared signals',
    component: OrganizationSSF,
    parameters: { mockDate: '2026-10-23T12:00:00Z' },
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me': user,
                '/api/organizations/@current': user.organization,
                '/api/organizations/:id/ssf': { ...SSF_SETTINGS, enabled: false },
                '/api/organizations/:id/ssf/connections': [],
                '/api/organizations/:id/ssf/streams': [],
            },
            patch: {
                '/api/organizations/:id/ssf/configuration': async ({ request }) => [
                    200,
                    { ...SSF_SETTINGS, ...((await request.json()) as object) },
                ],
                '/api/organizations/:id/ssf/streams/:stream': async ({ request }) => [
                    200,
                    { ...SSF_INCOMING_STREAM, ...((await request.json()) as object) },
                ],
                '/api/organizations/:id/ssf/connections/:connection': async ({ request }) => [
                    200,
                    { ...SSF_INCOMING_CONNECTION, ...((await request.json()) as object) },
                ],
            },
            post: {
                '/api/organizations/:id/ssf/connections': [201, SSF_INCOMING_CONNECTION],
                '/api/organizations/:id/ssf/connections/:connection/rotate_token': {
                    token: 'phssf_example_not_a_real_credential',
                },
                '/api/organizations/:id/ssf/connections/:connection/refresh': SSF_INCOMING_CONNECTION,
                '/api/organizations/:id/ssf/streams': [201, SSF_INCOMING_STREAM],
                '/api/organizations/:id/ssf/streams/:stream/verify': {
                    ...SSF_INCOMING_STREAM,
                    verification_pending: true,
                },
                '/api/organizations/:id/ssf/streams/:stream/provision': SSF_INCOMING_STREAM,
                '/api/organizations/:id/ssf/streams/:stream/status': SSF_INCOMING_STREAM,
                '/api/organizations/:id/ssf/rotate_key': SSF_SETTINGS,
            },
        }),
    ],
    render: () => (
        <div className="p-4 max-w-240">
            <OrganizationSSF />
        </div>
    ),
}
export default meta

type Story = StoryObj<typeof OrganizationSSF>

export const Unconfigured: Story = {}

export const Configured: Story = { decorators: [mswDecorator(configured)] }

export const StandalonePage: Story = {
    decorators: [mswDecorator(configured)],
    parameters: { layout: 'fullscreen' },
    render: () => {
        router.actions.push(urls.settings('organization-ssf'))
        return <App />
    },
}

export const NeedsUpgrade: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me': { ...user, organization: { ...user.organization, available_product_features: [] } },
                '/api/organizations/@current': { ...user.organization, available_product_features: [] },
                '/api/billing': {
                    ...billingJson,
                    products: billingJson.products.map((product, index) =>
                        index === 0
                            ? {
                                  ...product,
                                  features: [
                                      ...product.features,
                                      { key: AvailableFeature.SSF, name: 'Shared Signals Framework (SSF)' },
                                  ],
                              }
                            : product
                    ),
                },
            },
        }),
    ],
}

export const ReadOnly: Story = {
    decorators: [
        mswDecorator({
            get: {
                ...configured.get,
                '/api/users/@me': {
                    ...user,
                    organization: { ...user.organization, membership_level: OrganizationMembershipLevel.Member },
                },
                '/api/organizations/@current': {
                    ...user.organization,
                    membership_level: OrganizationMembershipLevel.Member,
                },
            },
        }),
    ],
}

export const Narrow: Story = {
    decorators: [mswDecorator(configured)],
    render: () => (
        <div className="p-4 w-130">
            <OrganizationSSF />
        </div>
    ),
}

export const FailedSetup: Story = {
    decorators: [
        mswDecorator({
            get: {
                ...configured.get,
                '/api/organizations/:id/ssf/streams': [
                    {
                        ...SSF_INCOMING_STREAM,
                        status: SSFStreamStatusEnumApi.Failed,
                        last_error: 'The transmitter returned HTTP 401. Check its URL and API credentials.',
                    },
                ],
            },
        }),
    ],
}

export const LoadFailure: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/organizations/:id/ssf': () => [500, { detail: 'Could not load configuration.' }] },
        }),
    ],
}
