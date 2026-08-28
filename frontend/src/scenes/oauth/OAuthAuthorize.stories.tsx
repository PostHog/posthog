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
                // The logic loads projects per organization for users that have organizations
                '/api/organizations/:organization_id/projects/': {
                    results: [
                        {
                            id: 1,
                            name: 'Default Project',
                            organization: '1',
                        },
                    ],
                },
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

// Identity-only request (openid/email/profile): permissions render as a plain checkmark list
// with no access selectors and no bulk actions.
export const DefaultScopes: Story = {
    render: () => {
        useDelayedOnMountEffect(() => pushAuthorize())
        return <App />
    },
}

// Explicit request where every requested scope is required: rows render as a plain locked
// checkmark list (no access selectors) and the bulk actions are hidden, since there is nothing
// to choose.
export const AllScopesRequired: Story = {
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

// Broad/deferred request (nothing required): every row gets a No access / Read / Write selector
// capped at the requested level, plus the Select all / Read-only / Deselect all bulk actions.
// This is the MCP case.
export const AllScopesOptional: Story = {
    decorators: [withOAuthApplication({ required_scopes: [] })],
    render: () => {
        useDelayedOnMountEffect(() => pushAuthorize('experiment:read experiment:write query:read feature_flag:write'))
        return <App />
    },
}

// Mixed: feature_flag:write is required but only read was requested (locked at write), and
// experiment:read is required but unrequested (an extra locked row). Both render in the
// checkmark list with a "Required" tag, while the rest keep their access selectors.
export const WithRequiredScopes: Story = {
    decorators: [withOAuthApplication({ required_scopes: ['experiment:read', 'feature_flag:write'] })],
    render: () => {
        useDelayedOnMountEffect(() => pushAuthorize('feature_flag:read query:read dashboard:write'))
        return <App />
    },
}

// A required read floor below a requested write: the row keeps its selector but "No access" is
// disabled — the user can drop the grant to read, never below the floor.
export const RequiredReadFloorWithOptionalWrite: Story = {
    decorators: [withOAuthApplication({ required_scopes: ['feature_flag:read'] })],
    render: () => {
        useDelayedOnMountEffect(() => pushAuthorize('feature_flag:write insight:write query:read'))
        return <App />
    },
}

// Wildcard request: a single "All PostHog data" row where Read expands to every grantable
// object's read scope and Write grants `*`.
export const WildcardScope: Story = {
    decorators: [withOAuthApplication({ required_scopes: [] })],
    render: () => {
        useDelayedOnMountEffect(() => pushAuthorize('*'))
        return <App />
    },
}

// A long optional list (every scope the PostHog MCP server supports) — the case the bulk
// actions exist for.
export const ManyOptionalScopes: Story = {
    decorators: [withOAuthApplication({ required_scopes: [] })],
    render: () => {
        useDelayedOnMountEffect(() =>
            pushAuthorize(
                'openid profile email user:read user:write organization:read project:read project:write ' +
                    'feature_flag:read feature_flag:write experiment:read experiment:write insight:read ' +
                    'insight:write dashboard:read dashboard:write query:read survey:read survey:write ' +
                    'event_definition:read event_definition:write error_tracking:read logs:read tracing:read'
            )
        )
        return <App />
    },
}
