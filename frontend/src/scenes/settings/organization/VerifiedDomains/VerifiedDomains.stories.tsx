import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { AvailableFeature, BillingFeatureType, OrganizationDomainType } from '~/types'

function makeFeatures(...features: AvailableFeature[]): BillingFeatureType[] {
    return features.map((f) => ({ key: f, name: f }))
}

function mockUserWithFeatures(...features: AvailableFeature[]): typeof MOCK_DEFAULT_USER {
    return {
        ...MOCK_DEFAULT_USER,
        organization: {
            ...MOCK_DEFAULT_ORGANIZATION,
            available_product_features: makeFeatures(...features),
        },
    }
}

function domainsResponse(domains: OrganizationDomainType[]): Record<string, unknown> {
    return { count: domains.length, next: null, previous: null, results: domains }
}

const CLOUD_PREFLIGHT = {
    ...preflightJson,
    cloud: true,
    realm: 'cloud',
    available_social_auth_providers: {
        github: true,
        gitlab: false,
        'google-oauth2': true,
        saml: false,
    },
}

const VERIFIED_DOMAIN_WITH_SAML_SCIM: OrganizationDomainType = {
    id: '1',
    domain: 'posthog.com',
    is_verified: true,
    verified_at: '2024-01-01T00:00:00Z',
    verification_challenge: 'abc',
    jit_provisioning_enabled: true,
    sso_enforcement: 'google-oauth2',
    has_saml: true,
    saml_entity_id: 'https://idp.posthog.com',
    saml_acs_url: 'https://idp.posthog.com/acs',
    saml_x509_cert: 'cert',
    scim_enabled: true,
    scim_base_url: 'https://posthog.com/scim/v2',
}

const VERIFIED_DOMAIN_NO_SAML_SCIM: OrganizationDomainType = {
    id: '2',
    domain: 'posthog.dev',
    is_verified: true,
    verified_at: '2024-01-01T00:00:00Z',
    verification_challenge: 'def',
    jit_provisioning_enabled: false,
    sso_enforcement: '',
    has_saml: false,
    saml_entity_id: '',
    saml_acs_url: '',
    saml_x509_cert: '',
    scim_enabled: false,
}

const UNVERIFIED_DOMAIN: OrganizationDomainType = {
    id: '3',
    domain: 'pending.com',
    is_verified: false,
    verified_at: '',
    verification_challenge: 'ghi',
    jit_provisioning_enabled: false,
    sso_enforcement: '',
    has_saml: false,
    saml_entity_id: '',
    saml_acs_url: '',
    saml_x509_cert: '',
    scim_enabled: false,
}

const ALL_FEATURES = [
    AvailableFeature.AUTOMATIC_PROVISIONING,
    AvailableFeature.SSO_ENFORCEMENT,
    AvailableFeature.SAML,
    AvailableFeature.SCIM,
]

type Story = StoryObj<typeof App>
const meta: Meta<typeof App> = {
    title: 'Scenes-App/Settings/Authentication Domains',
    component: App,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        featureFlags: STORYBOOK_FEATURE_FLAGS,
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': CLOUD_PREFLIGHT,
                '/api/projects/:id/integrations': { results: [] },
                '/api/organizations/:id/integrations': { results: [] },
                '/api/environments/:team_id/conversations/': { results: [] },
                '/api/user_home_settings/@me/': {},
            },
            patch: {
                '/api/projects/:id': async (req, res, ctx) => {
                    const newTeamSettings = { ...MOCK_DEFAULT_TEAM, ...(await req.json()) }
                    return res(ctx.json(newTeamSettings))
                },
            },
        }),
    ],
    render: () => {
        useEffect(() => {
            router.actions.push(urls.settings('organization-authentication'))
        }, [])
        return <App />
    },
}
export default meta

export const NoDomains: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me': () => [200, mockUserWithFeatures(...ALL_FEATURES)],
                '/api/organizations/:id/domains': domainsResponse([]),
            },
        }),
    ],
}

export const OneUnverifiedDomain: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me': () => [200, mockUserWithFeatures(...ALL_FEATURES)],
                '/api/organizations/:id/domains': domainsResponse([UNVERIFIED_DOMAIN]),
            },
        }),
    ],
}

export const BoostNeedsUpgrade: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me': () => [
                    200,
                    mockUserWithFeatures(AvailableFeature.AUTOMATIC_PROVISIONING, AvailableFeature.SSO_ENFORCEMENT),
                ],
                '/api/organizations/:id/domains': domainsResponse([VERIFIED_DOMAIN_NO_SAML_SCIM]),
            },
        }),
    ],
}

export const EnterpriseMixed: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me': () => [200, mockUserWithFeatures(...ALL_FEATURES)],
                '/api/organizations/:id/domains': domainsResponse([
                    VERIFIED_DOMAIN_WITH_SAML_SCIM,
                    VERIFIED_DOMAIN_NO_SAML_SCIM,
                    UNVERIFIED_DOMAIN,
                ]),
            },
        }),
    ],
}
