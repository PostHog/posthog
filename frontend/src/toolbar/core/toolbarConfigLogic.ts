import { actions, afterMount, beforeUnmount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { combineUrl, encodeParams } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toolbarLogger } from '~/toolbar/core/toolbarLogger'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/core/toolbarPosthogJS'
import { ToolbarProps } from '~/types'

import {
    cleanToolbarAuthHash,
    generatePKCE,
    LOCALSTORAGE_KEY,
    OAUTH_LOCALSTORAGE_KEY,
    PKCE_STORAGE_KEY,
    readToolbarAuthHash,
} from '../utils'
import { withTokenRefresh } from './toolbarAuth'
import type { toolbarConfigLogicType } from './toolbarConfigLogicType'

export const toolbarConfigLogic = kea<toolbarConfigLogicType>([
    path(['toolbar', 'core', 'toolbarConfigLogic']),
    props({} as ToolbarProps),

    actions({
        authenticate: true,
        logout: true,
        tokenExpired: true,
        clearUserIntent: true,
        showButton: true,
        hideButton: true,
        persistConfig: true,
        setOAuthTokens: (accessToken: string, refreshToken: string, clientId: string) => ({
            accessToken,
            refreshToken,
            clientId,
        }),
        setAuthStatus: (status: 'idle' | 'checking' | 'authenticating' | 'error') => ({ status }),
        openUiHostConfigModal: true,
        closeUiHostConfigModal: true,
    }),

    reducers(({ props }) => ({
        // TRICKY: We cache a copy of the props. This allows us to connect the logic without passing the props in - only the top level caller has to do this.
        props: [props],
        accessToken: [
            props.accessToken || null,
            {
                setOAuthTokens: (_, { accessToken }) => accessToken,
                logout: () => null,
                tokenExpired: () => null,
            },
        ],
        refreshToken: [
            props.refreshToken || null,
            {
                setOAuthTokens: (_, { refreshToken }) => refreshToken,
                logout: () => null,
                tokenExpired: () => null,
            },
        ],
        clientId: [
            props.clientId || null,
            {
                setOAuthTokens: (_, { clientId }) => clientId,
                logout: () => null,
                tokenExpired: () => null,
            },
        ],
        actionId: [props.actionId || null, { logout: () => null, clearUserIntent: () => null }],
        experimentId: [props.experimentId || null, { logout: () => null, clearUserIntent: () => null }],
        productTourId: [props.productTourId || null, { logout: () => null, clearUserIntent: () => null }],
        userIntent: [props.userIntent || null, { logout: () => null, clearUserIntent: () => null }],
        buttonVisible: [true, { showButton: () => true, hideButton: () => false, logout: () => false }],
        authStatus: [
            'idle' as 'idle' | 'checking' | 'authenticating' | 'error',
            { setAuthStatus: (_, { status }) => status },
        ],
        uiHostConfigModalVisible: [false, { openUiHostConfigModal: () => true, closeUiHostConfigModal: () => false }],
    })),

    selectors({
        posthog: [(s) => [s.props], (props) => props.posthog ?? null],
        // PostHog app URL used for OAuth and navigation links.
        uiHost: [
            (s) => [s.props],
            (props: ToolbarProps): string => {
                // Explicit uiHost passed from the PostHog app (authorizedUrlListLogic) wins —
                // it's window.location.origin of the app itself, so it's always correct even
                // for reverse-proxy customers who haven't set ui_host in posthog.init().
                if (props.uiHost) {
                    // Validate scheme to prevent javascript:/data: XSS via crafted hash params
                    try {
                        const parsed = new URL(props.uiHost)
                        if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
                            return props.uiHost.replace(/\/+$/, '')
                        }
                    } catch {
                        toolbarLogger.warn('config', 'Invalid uiHost URL provided', { uiHost: props.uiHost })
                    }
                }

                // requestRouter.uiHost honours explicit ui_host config and derives from
                // api_host for Cloud (strips the .i. ingestion infix).
                const uiHost = (props.posthog as any)?.requestRouter?.uiHost as string | undefined
                if (uiHost) {
                    return uiHost.replace(/\/+$/, '')
                }

                // Fallback for old posthog-js without requestRouter.
                if (props.posthog?.config?.ui_host) {
                    return props.posthog.config.ui_host.replace(/\/+$/, '')
                }
                if (props.apiURL) {
                    return props.apiURL.replace(/\/+$/, '')
                }
                return window.location.origin
            },
        ],
        // API host for JS and static assets (CSS)
        // Uses posthog.config.api_host if available, otherwise falls back to props.apiURL for backwards compatibility
        apiHost: [
            (s) => [s.props],
            (props: ToolbarProps): string => {
                if (props.posthog?.config?.api_host) {
                    return props.posthog.config.api_host.replace(/\/+$/, '')
                }

                // Fallback: if apiURL prop is set, use it (backwards compatibility)
                if (props.apiURL) {
                    return props.apiURL.replace(/\/+$/, '')
                }

                // Final fallback: current origin
                return window.location.origin
            },
        ],
        dataAttributes: [(s) => [s.props], (props): string[] => props.dataAttributes ?? []],
        isAuthenticated: [(s) => [s.accessToken], (accessToken) => !!accessToken],
        toolbarFlagsKey: [(s) => [s.props], (props): string | undefined => props.toolbarFlagsKey],
    }),

    listeners(({ values, actions }) => ({
        authenticate: async () => {
            toolbarLogger.info('auth', 'Authentication initiated')

            // If the uiHost check found a problem, open the config modal instead of proceeding.
            if (values.authStatus === 'error') {
                toolbarPosthogJS.capture('toolbar ui host config modal opened', { ui_host: values.uiHost })
                actions.openUiHostConfigModal()
                return
            }

            // Don't start OAuth while the reachability check is still in flight.
            if (values.authStatus === 'checking' || values.authStatus === 'authenticating') {
                return
            }

            toolbarPosthogJS.capture('toolbar authenticate', { is_authenticated: values.isAuthenticated })
            actions.persistConfig()

            let verifier: string
            let challenge: string
            try {
                const pkce = await generatePKCE()
                verifier = pkce.verifier
                challenge = pkce.challenge
            } catch (e) {
                captureToolbarException(e, 'pkce_generation')
                lemonToast.error('Failed to start authentication. Ensure you are on a secure (HTTPS) page.')
                return
            }
            const pkcePayload = JSON.stringify({ verifier, ts: Date.now() })
            localStorage.setItem(PKCE_STORAGE_KEY, pkcePayload)

            // Strip __posthog hash params before building the redirect URL.
            // posthog-js reads these at load time but never cleans them from the URL.
            // Including them would cause a re-initialization loop after OAuth callback.
            const hash = window.location.hash
                .replace(/[#&]__posthog=[^&]*/g, '')
                .replace(/[#&]__posthog_toolbar=[^&]*/g, '')
                .replace(/^&/, '#')
                .replace(/^#$/, '')
            const redirect = encodeURIComponent(
                window.location.origin + window.location.pathname + window.location.search + hash
            )
            const codeChallenge = encodeURIComponent(challenge)
            window.location.href = `${values.uiHost}/toolbar_oauth/authorize/?redirect=${redirect}&code_challenge=${codeChallenge}`
        },
        logout: () => {
            toolbarLogger.info('auth', 'User logged out')
            toolbarPosthogJS.capture('toolbar logout')
            localStorage.removeItem(LOCALSTORAGE_KEY)
            localStorage.removeItem(OAUTH_LOCALSTORAGE_KEY)
            localStorage.removeItem(PKCE_STORAGE_KEY)
            cleanToolbarAuthHash()
        },
        tokenExpired: () => {
            toolbarPosthogJS.capture('toolbar token expired')
            toolbarLogger.warn('auth', 'Session expired, clearing session')
            if (values.props.source !== 'localstorage') {
                lemonToast.error('Please re-authenticate to continue using the toolbar.')
            }
            localStorage.removeItem(OAUTH_LOCALSTORAGE_KEY)
            actions.persistConfig()
        },
        setOAuthTokens: () => {
            actions.persistConfig()
        },
        persistConfig: () => {
            // Most params we don't change, only those that we may have modified during the session
            const toolbarParams: ToolbarProps = {
                ...values.props,
                accessToken: values.accessToken ?? undefined,
                refreshToken: values.refreshToken ?? undefined,
                clientId: values.clientId ?? undefined,
                actionId: values.actionId ?? undefined,
                experimentId: values.experimentId ?? undefined,
                productTourId: values.productTourId ?? undefined,
                userIntent: values.userIntent ?? undefined,
                posthog: undefined,
            }

            localStorage.setItem(LOCALSTORAGE_KEY, JSON.stringify(toolbarParams))

            // Persist OAuth tokens separately so they survive posthog-js overwriting LOCALSTORAGE_KEY
            // when re-launching from a URL hash
            if (values.accessToken) {
                localStorage.setItem(
                    OAUTH_LOCALSTORAGE_KEY,
                    JSON.stringify({
                        accessToken: values.accessToken,
                        refreshToken: values.refreshToken,
                        clientId: values.clientId,
                    })
                )
            } else {
                localStorage.removeItem(OAUTH_LOCALSTORAGE_KEY)
            }
        },
    })),

    afterMount(({ props, values, actions, cache }) => {
        // Read hash params WITHOUT modifying the URL. The URL cleanup is deferred
        // to avoid triggering SPA routers that watch for history.replaceState changes
        // and could destroy/re-mount the page (and the toolbar) mid-initialization.
        const authParams = readToolbarAuthHash()
        if (authParams) {
            // Defer hash cleanup: some SPAs re-apply the original URL on initial render,
            // so we retry after a short delay as well.
            cache.hashRetryTimeout = setTimeout(cleanToolbarAuthHash, 500)
        }

        restoreOAuthTokens(!!authParams, values, actions)
        maybeMigrateTemporaryToken(!!authParams, props, values, actions)
        initInstrumentation(props, values)

        // Verify uiHost reachability, then exchange the OAuth code if present.
        // When uiHost was explicitly passed from the PostHog app it's always correct — skip check.
        // Otherwise always check: token_endpoint and redirect_uri are derived from uiHost,
        // so a wrong uiHost means the exchange will silently fail.
        if (!props.uiHost) {
            verifyUiHostReachability(props, values, actions, authParams)
        } else if (authParams) {
            startCodeExchange(values.uiHost, authParams, actions)
        }
    }),

    beforeUnmount(({ cache }) => {
        if (cache.hashRetryTimeout !== undefined) {
            clearTimeout(cache.hashRetryTimeout)
        }
        cleanToolbarAuthHash()
    }),
])

// ---------------------------------------------------------------------------
// afterMount helpers — extracted to keep the mount handler readable
// ---------------------------------------------------------------------------

type TokenActions = {
    setOAuthTokens: (accessToken: string, refreshToken: string, clientId: string) => void
    setAuthStatus: (status: 'idle' | 'checking' | 'authenticating' | 'error') => void
}
type CheckActions = TokenActions & {
    openUiHostConfigModal: () => void
}

/** Restore OAuth tokens from a separate localStorage key that survives posthog-js overwrites. */
function restoreOAuthTokens(
    pendingCodeExchange: boolean,
    values: { accessToken: string | null },
    actions: TokenActions
): void {
    if (values.accessToken || pendingCodeExchange) {
        return
    }
    try {
        const stored = localStorage.getItem(OAUTH_LOCALSTORAGE_KEY)
        if (stored) {
            const { accessToken, refreshToken, clientId } = JSON.parse(stored)
            if (accessToken && refreshToken && clientId) {
                actions.setOAuthTokens(accessToken, refreshToken, clientId)
            }
        }
    } catch {
        toolbarLogger.warn('auth', 'Failed to parse stored OAuth tokens from localStorage')
    }
}

/**
 * Migrate users from the old temporaryToken flow to OAuth.
 * TODO(@fcgomes): Remove after September 2026 — gives users 6 months to re-authenticate.
 */
function maybeMigrateTemporaryToken(
    pendingCodeExchange: boolean,
    props: ToolbarProps,
    values: { accessToken: string | null },
    actions: { tokenExpired: () => void }
): void {
    if (!values.accessToken && props.temporaryToken && !pendingCodeExchange) {
        actions.tokenExpired()
    }
}

/** Set up PostHog instrumentation and capture the "toolbar loaded" event. */
function initInstrumentation(
    props: ToolbarProps,
    values: { isAuthenticated: boolean; uiHost: string; apiHost: string }
): void {
    if (props.distinctId) {
        toolbarPosthogJS.identify(props.distinctId, props.userEmail ? { email: props.userEmail } : {})
    }

    if (props.instrument) {
        toolbarPosthogJS.opt_in_capturing()
    }

    const loadStart = (window as any).__posthog_toolbar_load_start as number | undefined
    const loadDurationMs = loadStart ? Math.round(performance.now() - loadStart) : undefined

    toolbarPosthogJS.capture('toolbar loaded', {
        is_authenticated: values.isAuthenticated,
        source: props.source || 'unknown',
        ui_host: values.uiHost,
        api_host: values.apiHost,
        ui_host_explicit: !!props.uiHost,
        ui_host_matches_api_host: values.uiHost === values.apiHost,
        load_duration_ms: loadDurationMs,
    })
}

function classifyFetchError(error: unknown): string {
    if (error instanceof DOMException && error.name === 'AbortError') {
        return 'timeout'
    }
    if (error instanceof TypeError) {
        return 'network_or_cors'
    }
    if (error instanceof Error && error.message.startsWith('HTTP ')) {
        return 'http_error'
    }
    return 'unknown'
}

/**
 * Run a CORS HEAD check against the PostHog app to verify uiHost is reachable.
 * If a pending OAuth code exchange exists, it runs after the check succeeds
 * (or shows the config modal on failure).
 */
function verifyUiHostReachability(
    props: ToolbarProps,
    values: { uiHost: string; apiHost: string; isAuthenticated: boolean },
    actions: CheckActions,
    authParams: { code: string; clientId: string } | null
): void {
    actions.setAuthStatus('checking')

    const uiHostSource = (props.posthog as any)?.requestRouter?.uiHost
        ? 'request_router'
        : props.posthog?.config?.ui_host
          ? 'posthog_config'
          : props.posthog?.config?.api_host
            ? 'posthog_api_host'
            : 'window_origin'

    const checkBaseProps = {
        ui_host: values.uiHost,
        api_host: values.apiHost,
        ui_host_source: uiHostSource,
        is_authenticated: values.isAuthenticated,
    }

    const checkStart = Date.now()
    void fetch(`${values.uiHost}/toolbar_oauth/check`, {
        method: 'HEAD',
        mode: 'cors',
        signal: AbortSignal.timeout(5000),
    })
        .then((response) => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`)
            }
            actions.setAuthStatus('idle')
            toolbarPosthogJS.capture('toolbar ui host check', {
                ...checkBaseProps,
                status: 'ok',
                duration_ms: Date.now() - checkStart,
            })

            if (authParams) {
                startCodeExchange(values.uiHost, authParams, actions)
            }
        })
        .catch((error: unknown) => {
            actions.setAuthStatus('error')
            captureToolbarException(error, 'ui_host_check', {
                error_type: classifyFetchError(error),
            })
            toolbarPosthogJS.capture('toolbar ui host check', {
                ...checkBaseProps,
                status: 'error',
                error_type: classifyFetchError(error),
                duration_ms: Date.now() - checkStart,
            })

            if (authParams) {
                actions.openUiHostConfigModal()
            }
        })
}

/** Exchange an OAuth authorization code for access + refresh tokens. */
function startCodeExchange(
    uiHost: string,
    authParams: { code: string; clientId: string },
    actions: TokenActions
): void {
    void exchangeCodeForTokens(
        `${uiHost}/oauth/token/`,
        `${uiHost}/toolbar_oauth/callback`,
        authParams.code,
        authParams.clientId,
        actions
    ).then((succeeded) => {
        if (!succeeded) {
            // Code exchange failed (stale code, expired PKCE, network error).
            // Fall back to stored OAuth tokens so users don't have to
            // re-authenticate when the hash wasn't cleaned properly.
            restoreOAuthTokens(false, { accessToken: null }, actions)
        }
    })
}

// ---------------------------------------------------------------------------
// Token exchange
// ---------------------------------------------------------------------------

const PKCE_TTL_MS = 10 * 60 * 1000 // 10 minutes

async function exchangeCodeForTokens(
    tokenEndpoint: string,
    redirectUri: string,
    code: string,
    clientId: string,
    actions: TokenActions
): Promise<boolean> {
    actions.setAuthStatus('authenticating')

    let pkceData: { verifier?: string; ts?: number } = {}
    try {
        const raw = localStorage.getItem(PKCE_STORAGE_KEY)
        pkceData = JSON.parse(raw || '{}')
    } catch {
        toolbarLogger.warn('auth', 'Failed to parse PKCE data from localStorage')
    }
    localStorage.removeItem(PKCE_STORAGE_KEY)

    if (!pkceData.verifier) {
        toolbarLogger.warn('auth', 'No PKCE verifier found, cannot exchange code')
        actions.setAuthStatus('idle')
        return false
    }
    if (pkceData.ts && Date.now() - pkceData.ts > PKCE_TTL_MS) {
        toolbarLogger.warn('auth', 'PKCE verifier expired')
        actions.setAuthStatus('idle')
        return false
    }

    const body = new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: clientId,
        code,
        redirect_uri: redirectUri,
        code_verifier: pkceData.verifier,
    })

    const startTime = performance.now()
    try {
        const res = await fetch(tokenEndpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body.toString(),
        })
        const data = await res.json()
        if (data.access_token && data.refresh_token) {
            toolbarPosthogJS.capture('toolbar oauth exchange', {
                status: 'success',
                duration_ms: Math.round(performance.now() - startTime),
            })
            actions.setOAuthTokens(data.access_token, data.refresh_token, clientId)
            return true
        }
        toolbarPosthogJS.capture('toolbar oauth exchange', {
            status: 'error',
            error: data.error || 'unknown',
            duration_ms: Math.round(performance.now() - startTime),
        })
        toolbarLogger.error('auth', 'Token exchange failed', { error: data.error || data })
        captureToolbarException(new Error(`Token exchange failed: ${data.error || 'unknown'}`), 'token_exchange')
        lemonToast.error('Authentication failed. Please try again.')
        return false
    } catch (err) {
        toolbarPosthogJS.capture('toolbar oauth exchange', {
            status: 'network_error',
            duration_ms: Math.round(performance.now() - startTime),
        })
        toolbarLogger.error('auth', 'Token exchange network error')
        captureToolbarException(err, 'token_exchange_network')
        lemonToast.error('Authentication failed due to a network error. Please try again.')
        return false
    } finally {
        actions.setAuthStatus('idle')
    }
}

export async function toolbarFetch(
    url: string,
    method: string = 'GET',
    payload?: Record<string, any>,
    /*
     allows caller to control how the provided URL is altered before use
     if "full" then the payload and URL are taken apart and reconstructed
     if "use-as-provided" then the URL is used as-is, and the payload is not used
     this is because the heatmapLogic needs more control over how the query parameters are constructed
    */
    urlConstruction: 'full' | 'use-as-provided' = 'full'
): Promise<Response> {
    const logic = toolbarConfigLogic.findMounted()
    const accessToken = logic?.values.accessToken
    const host = logic?.values.uiHost

    if (!accessToken) {
        return new Response(JSON.stringify({ results: [] }), { status: 401 })
    }

    let fullUrl: string
    if (urlConstruction === 'use-as-provided') {
        fullUrl = url
    } else {
        const { pathname, searchParams } = combineUrl(url)
        fullUrl = `${host}${pathname}${encodeParams(searchParams, '?')}`
    }

    const headers: Record<string, string> = { Authorization: `Bearer ${accessToken}` }
    if (payload) {
        headers['Content-Type'] = 'application/json'
    }

    const startTime = performance.now()
    let didRetry = false

    let response = await fetch(fullUrl, {
        method,
        headers,
        ...(payload ? { body: JSON.stringify(payload) } : {}),
    })

    response = await withTokenRefresh(response, async (newAccessToken) => {
        didRetry = true
        const retryHeaders: Record<string, string> = { Authorization: `Bearer ${newAccessToken}` }
        if (payload) {
            retryHeaders['Content-Type'] = 'application/json'
        }
        return await fetch(fullUrl, {
            method,
            headers: retryHeaders,
            ...(payload ? { body: JSON.stringify(payload) } : {}),
        })
    })

    const durationMs = Math.round(performance.now() - startTime)
    const { pathname } = combineUrl(url)

    toolbarPosthogJS.capture('toolbar api request', {
        method,
        pathname,
        status: response.status,
        duration_ms: durationMs,
        did_token_retry: didRetry,
    })

    if (response.status === 403) {
        // The toolbar can't distinguish "token lost access" from "user switched projects" —
        // both are project-level access failures. Clear tokens and let the user re-auth
        // rather than auto-redirecting to /toolbar_oauth/authorize/ (which would use the
        // session's current team, potentially causing a "Domain not authorized" loop).
        toolbarConfigLogic.actions.tokenExpired()
    }
    return response
}

export interface ToolbarMediaUploadResponse {
    id: string
    image_location: string
    name: string
}

/** Upload media (images) from the toolbar. */
export async function toolbarUploadMedia(file: File): Promise<{ id: string; url: string; fileName: string }> {
    const logic = toolbarConfigLogic.findMounted()
    const accessToken = logic?.values.accessToken
    const apiHost = logic?.values.apiHost

    if (!accessToken || !apiHost) {
        throw new Error('Toolbar not authenticated')
    }

    const formData = new FormData()
    formData.append('image', file)

    const url = `${apiHost}/api/projects/@current/uploaded_media/`

    let response = await fetch(url, {
        method: 'POST',
        body: formData,
        headers: { Authorization: `Bearer ${accessToken}` },
    })

    response = await withTokenRefresh(response, async (newAccessToken) => {
        const retryFormData = new FormData()
        retryFormData.append('image', file)
        return await fetch(url, {
            method: 'POST',
            body: retryFormData,
            headers: { Authorization: `Bearer ${newAccessToken}` },
        })
    })

    if (response.status === 401) {
        toolbarConfigLogic.findMounted()?.actions.tokenExpired()
        throw new Error('Authentication expired')
    }

    if (response.status === 403) {
        toolbarConfigLogic.findMounted()?.actions.tokenExpired()
        const responseData = await response.json().catch(() => ({}))
        throw new Error(responseData.detail || 'Access denied')
    }

    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || `Upload failed: ${response.status}`)
    }

    const data: ToolbarMediaUploadResponse = await response.json()
    return {
        id: data.id,
        url: data.image_location,
        fileName: data.name,
    }
}
