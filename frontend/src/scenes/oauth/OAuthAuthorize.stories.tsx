import { Decorator, Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect, useRef } from 'react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

// Override the server-injected oauth_application context for a story. Set synchronously before
// the story (and its consent logic) mounts, and restored on unmount so story order can't leak.
function withOAuthApplication(overrides: Record<string, unknown>): Decorator {
    return function OAuthApplicationDecorator(Story): JSX.Element {
        const appContext = (window as any).POSTHOG_APP_CONTEXT
        const original = useRef<{ value: unknown }>()
        if (!original.current) {
            original.current = { value: appContext.oauth_application }
            appContext.oauth_application = { ...appContext.oauth_application, ...overrides }
        }
        useEffect(
            () => () => {
                appContext.oauth_application = original.current?.value
            },
            [appContext]
        )
        return <Story />
    }
}

const pushAuthorize = (scope?: string): void => {
    const params = new URLSearchParams({
        client_id: 'test-client-id',
        redirect_uri: 'https://app.example.com/oauth/callback',
        response_type: 'code',
        state: 'test-state',
        ...(scope ? { scope } : {}),
    })
    router.actions.push(`${urls.oauthAuthorize()}?${params.toString()}`)
}

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
        useDelayedOnMountEffect(() => pushAuthorize())
        return <App />
    },
}

// Explicit request where every requested scope is required: rows render as a plain locked list
// (no checkboxes) and the read-only toggle is hidden, since there is nothing to toggle.
export const WithScopes: Story = {
    decorators: [
        withOAuthApplication({
            required_scopes: ['experiment:read', 'experiment:write', 'query:read', 'feature_flag:write'],
        }),
    ],
    render: () => {
        useDelayedOnMountEffect(() => pushAuthorize('experiment:read experiment:write query:read feature_flag:write'))
        return <App />
    },
}

// Broad/deferred request (empty ceiling): nothing is required, so every row is deselectable and
// the read-only toggle is offered. This is the MCP case.
export const BroadFreePick: Story = {
    decorators: [withOAuthApplication({ required_scopes: [] })],
    render: () => {
        useDelayedOnMountEffect(() => pushAuthorize('experiment:read experiment:write query:read feature_flag:write'))
        return <App />
    },
}

// Mixed: feature_flag:write is required but only read was requested (renders locked at write),
// and experiment:read is required but unrequested (appears as an extra locked row). Because some
// requested scopes stay declinable, the checkboxes remain.
export const WithRequiredScopes: Story = {
    decorators: [withOAuthApplication({ required_scopes: ['experiment:read', 'feature_flag:write'] })],
    render: () => {
        useDelayedOnMountEffect(() => pushAuthorize('feature_flag:read query:read dashboard:write'))
        return <App />
    },
}
