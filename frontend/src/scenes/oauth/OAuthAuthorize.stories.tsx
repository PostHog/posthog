import { Decorator, Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect, useRef } from 'react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { API_SCOPES } from 'lib/scopes'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

// Every story shares one server-injected app context, so a key a story writes outlives it.
// Snapshot the listed keys synchronously before the story (and its consent logic) mounts, apply
// any override, and put the previous values back on unmount so story order can't leak.
function useAppContextOverride(keys: readonly string[], apply?: (appContext: any) => void): void {
    const appContext = (window as any).POSTHOG_APP_CONTEXT
    const original = useRef<Record<string, unknown>>()
    if (!original.current) {
        original.current = Object.fromEntries(keys.map((key) => [key, appContext[key]]))
        apply?.(appContext)
    }
    useEffect(
        () => () => {
            Object.assign(appContext, original.current)
        },
        [appContext]
    )
}

function withOAuthApplication(overrides: Record<string, unknown>): Decorator {
    return function OAuthApplicationDecorator(Story): JSX.Element {
        useAppContextOverride(['oauth_application'], (appContext) => {
            appContext.oauth_application = { ...appContext.oauth_application, ...overrides }
        })
        return <Story />
    }
}

// `pushAuthorize` writes the resolution the server would have sent, and it runs after the story
// mounts, so it has nowhere to register a cleanup. This decorator owns that key's restore.
const withScopeResolution: Decorator = function ScopeResolutionDecorator(Story): JSX.Element {
    useAppContextOverride(['oauth_scope_resolution'])
    return <Story />
}

// The visual-regression runner lets a fullscreen scene grow to its full content height, which
// would leave the scrolling permission column and the pinned action row out of the snapshot.
// Pin the app shell to a window-sized box so the snapshot shows what a person actually sees.
const withPinnedSceneHeight: Decorator = function PinnedSceneHeightDecorator(Story): JSX.Element {
    return (
        <>
            <style>{'.Navigation3000 { height: 640px !important; min-height: 0 !important; }'}</style>
            <Story />
        </>
    )
}

const pushAuthorize = (scope?: string, resolvedScopes?: string[]): void => {
    const appContext = (window as any).POSTHOG_APP_CONTEXT
    appContext.oauth_scope_resolution = {
        scopes: resolvedScopes ?? (scope ? scope.split(' ') : []),
        was_defaulted: !scope,
    }
    const params = new URLSearchParams({
        client_id: 'test-client-id',
        redirect_uri: 'https://app.example.com/oauth/callback',
        response_type: 'code',
        state: 'test-state',
        ...(scope ? { scope } : {}),
    })
    router.actions.push(`${urls.oauthAuthorize()}?${params.toString()}`)
}

// One story per rendering of the consent screen, not per scope combination: what a level pick
// grants, and how a required floor clamps it, is asserted in oauthAuthorizeLogic.test.ts, where a
// reader sees the result instead of inferring it from a screenshot.
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
        withScopeResolution,
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

// A client that sends no `scope` at all: the server defaults the request to the app's ceiling,
// so every row arrives selected at its highest level with the bulk actions available.
export const DefaultScopes: Story = {
    decorators: [withOAuthApplication({ required_scopes: [] })],
    render: () => {
        useDelayedOnMountEffect(() =>
            pushAuthorize(undefined, [
                'openid',
                'email',
                'profile',
                'feature_flag:write',
                'insight:write',
                'dashboard:write',
                'query:read',
            ])
        )
        return <App />
    },
}

// Identity-only grant: the client asked for scopes outside the app's ceiling, so the server
// resolved the request down to the OIDC scopes. Permissions render as a plain checkmark list
// with no access selectors and no bulk actions.
export const IdentityOnlyScopes: Story = {
    decorators: [withOAuthApplication({ required_scopes: [] })],
    render: () => {
        useDelayedOnMountEffect(() => pushAuthorize('openid email profile'))
        return <App />
    },
}

// The logo is a third-party icon this repo already serves, so the snapshot never reaches out to a
// host we do not control.
export const WithApplicationLogo: Story = {
    decorators: [withOAuthApplication({ name: 'Zapier', logo_uri: '/static/services/zapier.png' })],
    render: () => {
        useDelayedOnMountEffect(() => pushAuthorize())
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

// Wildcard request: a single "All PostHog data" row where Read expands to every grantable
// object's read scope and Write grants `*`.
export const WildcardScope: Story = {
    decorators: [withOAuthApplication({ required_scopes: [] })],
    render: () => {
        useDelayedOnMountEffect(() => pushAuthorize('*'))
        return <App />
    },
}

// Sets the server flag that says one of the user's organizations has access-control rules.
// The story below shows the notice this flag adds under the permission list.
const withAccessControls: Decorator = function AccessControlsDecorator(Story): JSX.Element {
    useAppContextOverride(['oauth_consent_access_controls_apply'], (appContext) => {
        appContext.oauth_consent_access_controls_apply = true
    })
    return <Story />
}

export const AccessControlsApply: Story = {
    decorators: [withAccessControls, withOAuthApplication({ required_scopes: [] })],
    render: () => {
        useDelayedOnMountEffect(() =>
            pushAuthorize(
                'openid profile email project:read feature_flag:read feature_flag:write insight:write query:read'
            )
        )
        return <App />
    },
}

const everyScopeRequest = ['openid', 'profile', 'email', ...API_SCOPES.map(({ key }) => `${key}:write`)].join(' ')

// The worst case for the layout: a client that asks for every scope PostHog has, which is one
// permission row per scope object. The rows scroll inside the card, and the action row keeps
// Cancel and Authorize on screen the whole way down.
export const EveryScopeRequested: Story = {
    decorators: [withPinnedSceneHeight, withOAuthApplication({ required_scopes: [] })],
    render: () => {
        useDelayedOnMountEffect(() => pushAuthorize(everyScopeRequest))
        return <App />
    },
}
