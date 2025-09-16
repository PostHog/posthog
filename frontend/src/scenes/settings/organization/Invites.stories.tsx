import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { MockSignature } from '~/mocks/utils'

const meta: Meta = {
    component: App,
    title: 'Scenes-Other/Org Member Invites',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: Object.values(FEATURE_FLAGS),
        pageUrl: urls.settings('organization-members'),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me': () => [
                    200,
                    {
                        ...MOCK_DEFAULT_USER,
                        organization: {
                            membership_level: OrganizationMembershipLevel.Owner,
                        },
                    },
                ],
                '/api/organizations/@current/': (): MockSignature => [
                    200,
                    { ...MOCK_DEFAULT_ORGANIZATION, membership_level: OrganizationMembershipLevel.Owner },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const CurrentUserIsOwner: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: false,
                    realm: 'hosted-clickhouse',
                    available_social_auth_providers: {
                        github: false,
                        gitlab: false,
                        'google-oauth2': false,
                        saml: false,
                    },
                },
            },
        }),
    ],
}

export const CurrentUserIsAdmin: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: false,
                    realm: 'hosted-clickhouse',
                    available_social_auth_providers: {
                        github: false,
                        gitlab: false,
                        'google-oauth2': false,
                        saml: false,
                    },
                },
                '/api/organizations/@current/': (): MockSignature => [
                    200,
                    { ...MOCK_DEFAULT_ORGANIZATION, membership_level: OrganizationMembershipLevel.Admin },
                ],
            },
        }),
    ],
}

export const CurrentUserIsMember: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: false,
                    realm: 'hosted-clickhouse',
                    available_social_auth_providers: {
                        github: false,
                        gitlab: false,
                        'google-oauth2': false,
                        saml: false,
                    },
                },
                '/api/organizations/@current/': (): MockSignature => [
                    200,
                    { ...MOCK_DEFAULT_ORGANIZATION, membership_level: OrganizationMembershipLevel.Member },
                ],
            },
        }),
    ],
}
