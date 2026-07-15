// PostHog embeddable widgets entry.
//
// Loads as a standalone ESM bundle in a FOREIGN document (e.g. the PostHog Code
// desktop app, which runs React 19 — a separate React copy and kea context live
// inside this bundle, rendered into a shadow root, exactly like the toolbar).
//
//   const { mountQueryEditor } = window.PostHogWidgets
//   const handle = mountQueryEditor(el, { query, onQueryChange, apiHost, getAccessToken, theme })
//   handle.update({ query, theme })
//   handle.unmount()
import '~/styles'
import './widgets.scss'

import { createRoot, Root } from 'react-dom/client'

import { setOAuthSessionOverride } from 'lib/oauth/oauthClient'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { initKea } from '~/initKea'
import { ErrorBoundary } from '~/layout/ErrorBoundary'

import { QueryEditorWidget, setWidgetAssetBaseUrl } from './QueryEditorWidget'
import { MountQueryEditorOptions, QueryEditorWidgetHandle } from './types'
import { WidgetInstanceStore } from './widgetStore'

// Never send telemetry from embedded widgets: posthog-js is not initialized here,
// and `posthog.capture`/`captureException` calls downstream become no-ops.
;(window as any).JS_POSTHOG_API_KEY = undefined

// The CSS sibling (widgets.css) is resolved relative to this module's URL.
// NOTE: deliberately NOT `new URL('./', import.meta.url)` — Vite statically
// rewrites that pattern into an emitted-asset URL at build time.
const moduleUrl: string = import.meta.url
setWidgetAssetBaseUrl(moduleUrl.slice(0, moduleUrl.lastIndexOf('/') + 1))

let keaInitialized = false

/**
 * One-time bootstrap shared by all widget mounts in this document:
 * - seed the in-memory OAuth session so lib/api targets `apiHost` with a bearer token
 * - initialize the kea context (kea is a singleton per JS realm — one context, keyed logics)
 */
function ensureBooted(options: MountQueryEditorOptions): void {
    const initialToken = options.personalApiKey ?? null

    setOAuthSessionOverride(
        {
            backendHost: options.apiHost.replace(/\/+$/, ''),
            clientId: 'posthog-widgets-embedded',
            accessToken: initialToken ?? '',
            refreshToken: '',
            expiresAt: Date.now() + 10 * 60 * 1000,
        },
        options.getAccessToken
    )

    if (options.getAccessToken && !initialToken) {
        // Fetch the real token ASAP; requests racing ahead of it will 401 once and
        // then be retried through the refresh path (which calls getAccessToken).
        void options.getAccessToken().then((token) => {
            if (token) {
                setOAuthSessionOverride(
                    {
                        backendHost: options.apiHost.replace(/\/+$/, ''),
                        clientId: 'posthog-widgets-embedded',
                        accessToken: token,
                        refreshToken: '',
                        expiresAt: Date.now() + 10 * 60 * 1000,
                    },
                    options.getAccessToken
                )
            }
        })
    }

    if (!keaInitialized) {
        // replaceInitialPathInWindow: false — never touch the host app's URL.
        initKea({ replaceInitialPathInWindow: false })
        keaInitialized = true
    }

    if (options.__unsafeMockContext) {
        const mock = options.__unsafeMockContext
        userLogic.mount()
        teamLogic.mount()
        // afterMount kicks off loadUser()/loadCurrentTeam(), which fail without
        // credentials and overwrite values with null — re-assert the mocks until
        // those in-flight loads have settled. Harness-only, so a timer is fine.
        const assertMocks = (): void => {
            if (!userLogic.values.user) {
                userLogic.actions.loadUserSuccess(mock.user as any)
            }
            if (!teamLogic.values.currentTeam) {
                teamLogic.actions.loadCurrentTeamSuccess(mock.team as any)
            }
        }
        assertMocks()
        setTimeout(assertMocks, 1000)
        setTimeout(assertMocks, 3000)
    }
}

export function mountQueryEditor(el: HTMLElement, options: MountQueryEditorOptions): QueryEditorWidgetHandle {
    ensureBooted(options)

    const store = new WidgetInstanceStore(options)
    const container = document.createElement('div')
    container.style.display = 'contents'
    el.appendChild(container)

    const reactRoot: Root = createRoot(container)
    reactRoot.render(
        <ErrorBoundary>
            <QueryEditorWidget store={store} />
        </ErrorBoundary>
    )

    return {
        update(partial) {
            store.update({
                ...(partial.query !== undefined ? { query: partial.query } : {}),
                ...(partial.onQueryChange !== undefined ? { onQueryChange: partial.onQueryChange } : {}),
                ...(partial.theme !== undefined ? { theme: partial.theme } : {}),
            })
        },
        unmount() {
            reactRoot.unmount()
            container.remove()
        },
    }
}

declare global {
    interface Window {
        PostHogWidgets?: {
            mountQueryEditor: typeof mountQueryEditor
        }
    }
}

window.PostHogWidgets = { mountQueryEditor }
