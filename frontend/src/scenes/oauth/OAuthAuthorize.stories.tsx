import { Decorator, Meta, StoryObj } from '@storybook/react'
import { useEffect, useRef } from 'react'

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

// Writes the scope resolution the server would have sent for the story's `oauthRequest`, before the scene mounts.
const withScopeResolution: Decorator = function ScopeResolutionDecorator(Story, { parameters }): JSX.Element {
    const { scope, resolvedScopes, alreadyGrantedScopes } = (parameters.oauthRequest ?? {}) as {
        scope?: string
        resolvedScopes?: string[]
        alreadyGrantedScopes?: string[]
    }
    useAppContextOverride(['oauth_scope_resolution'], (appContext) => {
        appContext.oauth_scope_resolution = {
            scopes: resolvedScopes ?? (scope ? scope.split(' ') : []),
            was_defaulted: !scope,
            already_granted_scopes: alreadyGrantedScopes ?? [],
        }
    })
    return <Story />
}

// The app shell has a `100vh` min-height, so when the viewport at capture time is taller than the
// card, the shell grows to the viewport and adds a blank strip below the card. Let the shell hug its
// content so only the card sets the height.
const withContentSceneHeight: Decorator = function ContentSceneHeightDecorator(Story): JSX.Element {
    return (
        <>
            <style>{'.Navigation3000 { min-height: 0 !important; }'}</style>
            <Story />
        </>
    )
}

// `pageUrl` opens the consent page on mount. A push 500 ms later first rendered the default route, and a
// capture could catch a leftover of it as a blank strip below the card.
const authorizeParameters = (scope?: string, resolvedScopes?: string[]): Record<string, unknown> => {
    const params = new URLSearchParams({
        client_id: 'test-client-id',
        redirect_uri: 'https://app.example.com/oauth/callback',
        response_type: 'code',
        state: 'test-state',
        ...(scope ? { scope } : {}),
    })
    return { pageUrl: `${urls.oauthAuthorize()}?${params.toString()}`, oauthRequest: { scope, resolvedScopes } }
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
                '/api/organizations/:organization_id/projects/': {
                    results: [
                        {
                            id: 1,
                            name: 'Default Project',
                            organization: '1',
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

// Both required scopes show a lock, and experiment:read is required without being requested.
export const FewPermissions: Story = {
    decorators: [withOAuthApplication({ required_scopes: ['experiment:read', 'feature_flag:write'] })],
    render: () => <App />,
    parameters: authorizeParameters('openid email feature_flag:read query:read dashboard:write insight:write'),
}

// The narrow width is an OAuth popup window, where group labels truncate.
export const ManyPermissions: Story = {
    decorators: [withContentSceneHeight, withOAuthApplication({ required_scopes: ['feature_flag:read'] })],
    render: () => <App />,
    parameters: {
        ...authorizeParameters(
            'openid profile email organization:read project:read project:write feature_flag:write ' +
                'experiment:write insight:write dashboard:write query:read survey:write ' +
                'event_definition:write error_tracking:read logs:read'
        ),
        testOptions: { viewportWidths: ['narrow', 'wide'] },
    },
}

export const StepUp: Story = {
    decorators: [withOAuthApplication({ required_scopes: [] })],
    render: () => <App />,
    parameters: {
        ...authorizeParameters('openid email insight:read dashboard:write feature_flag:write'),
        oauthRequest: {
            scope: 'openid email insight:read dashboard:write feature_flag:write',
            alreadyGrantedScopes: ['openid', 'email', 'insight:read', 'dashboard:read'],
        },
    },
}

export const FullAccess: Story = {
    decorators: [withOAuthApplication({ required_scopes: [] })],
    render: () => <App />,
    parameters: authorizeParameters('*'),
}

export const IdentityOnly: Story = {
    decorators: [withOAuthApplication({ required_scopes: [] })],
    render: () => <App />,
    parameters: authorizeParameters('openid email profile'),
}

// A client that sends no `scope` at all: the server defaults the request to the app's ceiling, and a
// banner says so.
export const DefaultScopes: Story = {
    decorators: [withContentSceneHeight, withOAuthApplication({ required_scopes: [] })],
    render: () => <App />,
    parameters: authorizeParameters(undefined, ['openid', 'email', 'profile', 'feature_flag:write', 'query:read']),
}

// The logo is a third-party icon this repo already serves, so the snapshot never reaches out to a
// host we do not control.
export const WithApplicationLogo: Story = {
    decorators: [withOAuthApplication({ name: 'Zapier', logo_uri: '/static/services/zapier.png' })],
    render: () => <App />,
    parameters: authorizeParameters(),
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
    render: () => <App />,
    parameters: authorizeParameters('openid feature_flag:write query:read'),
}

const withEmaIssuerConsent: Decorator = function EmaIssuerConsentDecorator(Story): JSX.Element {
    useAppContextOverride(['oauth_ema_issuer_consent'], (appContext) => {
        appContext.oauth_ema_issuer_consent = {
            scope: 'ema_issuer:manage',
            organizations: [
                { id: '1', name: 'Hedgebox', verified_domains: ['hedgebox.net'], disabled_reason: null },
                {
                    id: '2',
                    name: 'Hedgebox staging',
                    verified_domains: [],
                    disabled_reason: 'Only admins of this organization can set up enterprise-managed auth.',
                },
            ],
        }
    })
    return <Story />
}

export const EnterpriseManagedAuthSetup: Story = {
    decorators: [withContentSceneHeight, withEmaIssuerConsent, withOAuthApplication({ name: 'Claude' })],
    render: () => <App />,
    parameters: authorizeParameters('ema_issuer:manage', ['ema_issuer:manage']),
}

export const NoOrganization: Story = {
    decorators: [
        withOAuthApplication({ required_scopes: [] }),
        mswDecorator({
            get: {
                '/api/users/@me/': () => [
                    200,
                    {
                        uuid: '018e1b6b-0000-0000-0000-000000000002',
                        email: 'test@posthog.com',
                        first_name: 'Test',
                        organization: null,
                        organizations: [],
                        team: null,
                    },
                ],
            },
        }),
    ],
    render: () => <App />,
    parameters: { ...authorizeParameters(), testOptions: { snapshotBrowsers: [] } },
}
