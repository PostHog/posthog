import { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta = {
    title: 'Scenes-App/OAuth/Authorize',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        testOptions: {
            waitForSelector: '.max-w-2xl',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/': {
                    results: [
                        {
                            id: 1,
                            name: 'Default Project',
                            organization: {
                                id: '1',
                                name: 'Default Organization',
                                slug: 'default-org',
                            },
                        },
                        {
                            id: 2,
                            name: 'Analytics Project',
                            organization: {
                                id: '1',
                                name: 'Default Organization',
                                slug: 'default-org',
                            },
                        },
                    ],
                },
            },
            post: {
                '/oauth/authorize/': {
                    redirect_to: 'https://example.com/callback?code=test-auth-code&state=test-state',
                },
            },
        }),
    ],
}

export default meta

type Story = StoryObj<{}>

export const DefaultScopes: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            const params = new URLSearchParams({
                client_id: 'test-client-id',
                redirect_uri: 'https://example.com/callback',
                response_type: 'code',
                state: 'test-state',
            })
            router.actions.push(`${urls.oauthAuthorize()}?${params.toString()}`)
        })

        return <App />
    },
}

export const WithScopes: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            const appContext = (window as any).POSTHOG_APP_CONTEXT
            appContext.oauth_application = {
                ...appContext.oauth_application,
                // Explicit request: every requested scope is required, so all rows
                // render locked and the read-only toggle is hidden (it would be a no-op).
                required_scopes: ['experiment:read', 'experiment:write', 'query:read', 'feature_flag:write'],
            }
            const params = new URLSearchParams({
                client_id: 'test-client-id',
                redirect_uri: 'https://app.example.com/oauth/callback',
                response_type: 'code',
                state: 'test-state',
                scope: 'experiment:read experiment:write query:read feature_flag:write',
            })
            router.actions.push(`${urls.oauthAuthorize()}?${params.toString()}`)
        })

        return <App />
    },
}

export const BroadFreePick: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            const appContext = (window as any).POSTHOG_APP_CONTEXT
            appContext.oauth_application = {
                ...appContext.oauth_application,
                // Broad/deferred request (empty ceiling): nothing is required, so every
                // row is deselectable and the read-only toggle is offered. This is the MCP case.
                required_scopes: [],
            }
            const params = new URLSearchParams({
                client_id: 'test-client-id',
                redirect_uri: 'https://app.example.com/oauth/callback',
                response_type: 'code',
                state: 'test-state',
                scope: 'experiment:read experiment:write query:read feature_flag:write',
            })
            router.actions.push(`${urls.oauthAuthorize()}?${params.toString()}`)
        })

        return <App />
    },
}

export const WithRequiredScopes: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            const appContext = (window as any).POSTHOG_APP_CONTEXT
            appContext.oauth_application = {
                ...appContext.oauth_application,
                // feature_flag:write is required but the client only requested read,
                // so the row must render locked at the write level. experiment:read
                // is required and unrequested, so it appears as an extra locked row.
                required_scopes: ['experiment:read', 'feature_flag:write'],
            }
            const params = new URLSearchParams({
                client_id: 'test-client-id',
                redirect_uri: 'https://app.example.com/oauth/callback',
                response_type: 'code',
                state: 'test-state',
                scope: 'feature_flag:read query:read dashboard:write',
            })
            router.actions.push(`${urls.oauthAuthorize()}?${params.toString()}`)
        })

        return <App />
    },
}
