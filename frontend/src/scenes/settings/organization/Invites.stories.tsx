import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { OrganizationMembershipLevel, STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
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
        featureFlags: STORYBOOK_FEATURE_FLAGS,
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
                // This page also renders the member notifications section, which would otherwise
                // sit on a spinner and make the snapshot depend on timing.
                '/api/organizations/:id/notification_locks/': [
                    {
                        user_id: 1,
                        uuid: '0198aaaa-0000-4000-8000-000000000001',
                        first_name: 'Ada',
                        last_name: 'Kowalski',
                        email: 'ada@example.com',
                        organization_membership_level: 1,
                        editable: true,
                        locks: [],
                    },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
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
