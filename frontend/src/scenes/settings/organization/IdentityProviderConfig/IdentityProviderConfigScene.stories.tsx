import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { ConfigScopeEnumApi } from '~/generated/core/api.schemas'
import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { AvailableFeature } from '~/types'

interface StoryProps {
    configScope: ConfigScopeEnumApi
}

const IDENTITY_PROVIDER_CONFIG = {
    id: '0198aaaa-0000-4000-8000-000000000001',
    name: 'Example identity provider',
    domain_scope: 'all',
    config_scope: null,
    organization_domain_ids: [],
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    has_saml: true,
    saml_relay_state: '0198bbbb-0000-4000-8000-000000000001',
    saml_entity_id: 'https://idp.example.com',
    saml_acs_url: 'https://idp.example.com/sso',
    saml_x509_cert: '-----BEGIN CERTIFICATE-----\nEXAMPLE\n-----END CERTIFICATE-----',
    has_scim: true,
    scim_enabled: true,
    scim_base_url: 'https://app.posthog.com/scim/v2/0198cccc-0000-4000-8000-000000000001',
    scim_bearer_token: null,
    has_id_jag: true,
    id_jag_issuer_url: 'https://idp.example.com',
    id_jag_jwks_url: 'https://idp.example.com/.well-known/jwks.json',
    id_jag_allowed_clients: ['example-client'],
}

const USER_WITHOUT_IDENTITY_PROVIDER_FEATURES = {
    ...MOCK_DEFAULT_USER,
    organization: {
        ...MOCK_DEFAULT_ORGANIZATION,
        available_product_features: [],
    },
}

const USER_WITH_IDENTITY_PROVIDER_FEATURES = {
    ...MOCK_DEFAULT_USER,
    organization: {
        ...MOCK_DEFAULT_ORGANIZATION,
        available_product_features: [
            AvailableFeature.SAML,
            AvailableFeature.SCIM,
            AvailableFeature.XAA_AUTHENTICATION,
        ].map((feature) => ({ key: feature, name: feature })),
    },
}

type Story = StoryObj<(props: StoryProps) => JSX.Element>
const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Scenes-App/Settings/Identity provider configuration',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.SSO_SETTINGS_REDESIGN, FEATURE_FLAGS.XAA_AUTHENTICATION],
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
                '/api/users/@me': USER_WITH_IDENTITY_PROVIDER_FEATURES,
                '/api/projects/:id/integrations': { results: [] },
                '/api/organizations/:id/integrations': { results: [] },
                '/api/organizations/:id/identity_provider_configs/:configId': IDENTITY_PROVIDER_CONFIG,
                '/api/organizations/:id/domains': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: '0198dddd-0000-4000-8000-000000000001',
                            domain: 'example.com',
                            is_verified: true,
                            verified_at: '2026-08-01T00:00:00Z',
                            verification_challenge: 'challenge',
                            jit_provisioning_enabled: true,
                            sso_enforcement: 'saml',
                            scim_base_url: IDENTITY_PROVIDER_CONFIG.scim_base_url,
                        },
                        {
                            id: '0198dddd-0000-4000-8000-000000000002',
                            domain: 'pending.example.com',
                            is_verified: false,
                            verified_at: null,
                            verification_challenge: 'challenge',
                            jit_provisioning_enabled: false,
                            sso_enforcement: '',
                            scim_base_url: null,
                        },
                    ],
                },
            },
            patch: {
                '/api/organizations/:id/identity_provider_configs/:configId': async ({ request }) => [
                    200,
                    { ...IDENTITY_PROVIDER_CONFIG, ...((await request.json()) as object) },
                ],
            },
        }),
    ],
    render: ({ configScope }) => {
        router.actions.push(urls.identityProviderConfig(configScope, IDENTITY_PROVIDER_CONFIG.id))
        return <App />
    },
}
export default meta

const needsUpgradeDecorator = mswDecorator({
    get: { '/api/users/@me': USER_WITHOUT_IDENTITY_PROVIDER_FEATURES },
})

export const SAML: Story = { args: { configScope: ConfigScopeEnumApi.Saml } }
export const SAMLNeedsUpgrade: Story = {
    args: { configScope: ConfigScopeEnumApi.Saml },
    decorators: [needsUpgradeDecorator],
}
export const SCIM: Story = { args: { configScope: ConfigScopeEnumApi.Scim } }
export const XAA: Story = { args: { configScope: ConfigScopeEnumApi.Xaa } }
export const XAANeedsUpgrade: Story = {
    args: { configScope: ConfigScopeEnumApi.Xaa },
    decorators: [needsUpgradeDecorator],
}
