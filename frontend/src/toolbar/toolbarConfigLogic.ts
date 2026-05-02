import { actions, afterMount, beforeUnmount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { combineUrl, encodeParams } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ToolbarProps } from '~/types'

import { withTokenRefresh } from './toolbarAuth'
import type { toolbarConfigLogicType } from './toolbarConfigLogicType'
import {
    cleanToolbarAuthHash,
    generatePKCE,
    LOCALSTORAGE_KEY,
    OAUTH_LOCALSTORAGE_KEY,
    PKCE_STORAGE_KEY,
    readToolbarAuthHash,
} from './utils'

export type ApiHostSource = 'posthog_api_host' | 'api_url' | 'fallback_rejected' | 'fallback_absent'

export const toolbarConfigLogic = kea<toolbarConfigLogicType>([
    path(['toolbar', 'toolbarConfigLogic']),
    props({} as ToolbarProps),

    actions({
        authenticate: true,
        /** Proceed with the OAuth redirect after the user confirms the target domain. */
        confirmAuthenticate: true,
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
        openAuthConfirmModal: true,
        closeAuthConfirmModal: true,
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
        authConfirmModalVisible: [
            false,
            { openAuthConfirmModal: () => true, closeAuthConfirmModal: () => false, confirmAuthenticate: () => false },
        ],
    })),

    selectors({
        posthog: [(s) => [s.props], (props) => props.posthog ?? null],
        // PostHog app URL used for OAuth and navigation links.
        //
        // Every candidate (props.uiHost, requestRouter, config.ui_host, apiURL) is
        // sanitized via canonicalizeUiHost — it rejects non-http(s) schemes, URLs with
        // userinfo (which can visually spoof the target in confirmation dialogs), and
        // returns the canonical `origin` (lowercased hostname, no trailing slash, no
        // path/query/hash). This keeps every downstream comparison and display string
        // byte-for-byte consistent regardless of which branch resolved.
        uiHost: [
            (s) => [s.props],
            (props: ToolbarProps): string => {
                const propsUiHost = canonicalizeUiHost(props.uiHost)
                if (propsUiHost) {
                    return propsUiHost
                }
                if (props.uiHost) {
                    toolbarLogger.warn('config', 'Invalid uiHost URL provided', { uiHost: props.uiHost })
                }

                // requestRouter.uiHost honours explicit ui_host config and derives from
                // api_host for Cloud (strips the .i. ingestion infix).
                const fromRouter = canonicalizeUiHost(
                    (props.posthog as any)?.requestRouter?.uiHost as string | undefined
                )
                if (fromRouter) {
                    return fromRouter
                }

                // Fallback for old posthog-js without requestRouter.
                const fromConfig = canonicalizeUiHost(props.posthog?.config?.ui_host)
                if (fromConfig) {
                    return fromConfig
                }
                const fromApi = canonicalizeUiHost(props.apiURL)
                if (fromApi) {
                    return fromApi
                }
                return window.location.origin
            },
        ],
        // Host for static assets (the toolbar CSS `<link href>`) and for the
        // `api_host` property emitted on toolbar telemetry. NEVER use for
        // authenticated API calls — uiHost is token-bound via restoreOAuthTokens,
        // apiHost is not, so sending bearer tokens here would let an attacker
        // redirect them via the apiURL hash param.
        //
        // Candidates are run through canonicalizeApiHost which rejects
        // non-http(s) schemes and userinfo URLs (blocks `javascript:` reaching
        // a <link href>), while preserving the URL path so reverse-proxy
        // deployments like `https://proxy/ingest` keep working.
        //
        // apiHostResolution carries the same value plus a `source` label so
        // telemetry can distinguish "fell back to origin because nothing was
        // supplied" (normal) from "fell back because supplied value was
        // rejected" (misconfiguration) without re-running the sanitizer.
        apiHostResolution: [
            (s) => [s.props],
            (props: ToolbarProps): { host: string; source: ApiHostSource } => {
                const rawConfig = props.posthog?.config?.api_host
                const fromConfig = canonicalizeApiHost(rawConfig)
                if (fromConfig) {
                    return { host: fromConfig, source: 'posthog_api_host' }
                }
                if (rawConfig) {
                    toolbarLogger.warn('config', 'Invalid posthog.config.api_host, rejected', {
                        api_host: rawConfig,
                    })
                }
                const rawApi = props.apiURL
                const fromApi = canonicalizeApiHost(rawApi)
                if (fromApi) {
                    return { host: fromApi, source: 'api_url' }
                }
                if (rawApi) {
                    toolbarLogger.warn('config', 'Invalid apiURL, rejected', { apiURL: rawApi })
                }
                return {
                    host: window.location.origin,
                    source: rawConfig || rawApi ? 'fallback_rejected' : 'fallback_absent',
                }
            },
        ],
        apiHost: [
            (s) => [s.apiHostResolution],
            (resolution: { host: string; source: ApiHostSource }): string => resolution.host,
        ],
        dataAttributes: [(s) => [s.props], (props): string[] => props.dataAttributes ?? []],
        isAuthenticated: [(s) => [s.accessToken], (accessToken) => !!accessToken],
        toolbarFlagsKey: [(s) => [s.props], (props): string | undefined => props.toolbarFlagsKey],
        // True when uiHost is a PostHog Cloud host (us/eu) — safe to skip the
        // "are you sure you want to authenticate here?" confirmation.
        isTrustedUiHost: [(s) => [s.uiHost], (uiHost: string): boolean => isPostHogCloudHost(uiHost)],
    }),

    listeners(({ values, actions }) => ({
        authenticate: () => {
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

            // Show the user which domain they'll be redirected to before proceeding.
            // This prevents phishing via crafted #__posthog= hash params with a
            // malicious uiHost — the user sees the target domain and can cancel.
            // Skip for PostHog Cloud (us/eu) where the target is already trusted.
            if (values.isTrustedUiHost) {
                actions.confirmAuthenticate()
                return
            }
            actions.openAuthConfirmModal()
        },
        confirmAuthenticate: async () => {
            // Re-check status because the modal can sit open arbitrarily long — the
            // reachability check may have flipped to 'error' while the user read the
            // dialog, and we must not redirect to an unreachable host.
            if (values.authStatus === 'error') {
                toolbarPosthogJS.capture('toolbar ui host config modal opened', { ui_host: values.uiHost })
                actions.openUiHostConfigModal()
                return
            }
            if (values.authStatus === 'checking' || values.authStatus === 'authenticating') {
                // Either the reachability HEAD is still pending or we're already redirecting.
                // Ignoring a second click avoids double PKCE generation and a race where
                // the second navigation cancels the first.
                return
            }

            toolbarLogger.info('auth', 'Authentication confirmed by user')
            toolbarPosthogJS.capture('toolbar authenticate', { is_authenticated: values.isAuthenticated })
            // Transition status BEFORE the async PKCE work so re-entrant calls bail early.
            actions.setAuthStatus('authenticating')
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
                actions.setAuthStatus('idle')
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
            // when re-launching from a URL hash.
            // Bind tokens to the uiHost they were issued for — prevents an attacker from
            // injecting a malicious uiHost via crafted hash params and silently exfiltrating
            // stored tokens to their domain.
            if (values.accessToken) {
                localStorage.setItem(
                    OAUTH_LOCALSTORAGE_KEY,
                    JSON.stringify({
                        accessToken: values.accessToken,
                        refreshToken: values.refreshToken,
                        clientId: values.clientId,
                        uiHost: values.uiHost,
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

        // Reachability check is a UX helper: it detects misconfigured / unreachable
        // uiHosts BEFORE the user clicks Authenticate so we can surface the config
        // modal. It is NOT a security boundary — an attacker-controlled host can
        // respond 200 to a CORS HEAD trivially. The real defenses are (1) the
        // confirmation modal for untrusted hosts, and (2) the uiHost-binding on
        // stored tokens.
        //
        // Skip the HEAD when:
        // - uiHost is a trusted PostHog Cloud host (always reachable, no value in
        //   probing; avoids false-positive errors for Cloud users behind strict
        //   corporate proxies that block CORS preflights)
        // - user is already authenticated AND there's no pending OAuth code (the
        //   existing session is valid; probing on every mount would degrade UX for
        //   self-hosted / SSO / reverse-proxy customers whose PostHog app works
        //   fine for real API calls but CORS-rejects the cheap HEAD)
        if (isPostHogCloudHost(values.uiHost)) {
            if (authParams) {
                startCodeExchange(values.uiHost, authParams, actions)
            }
            return
        }
        if (values.isAuthenticated && !authParams) {
            return
        }
        verifyUiHostReachability(props, values, actions, authParams)
    }),

    beforeUnmount(({ cache }) => {
        if (cache.hashRetryTimeout !== undefined) {
            clearTimeout(cache.hashRetryTimeout)
        }
        cleanToolbarAuthHash()
    }),
])

// Hostnames we trust enough to skip the authentication confirmation modal
// and the reachability check, and to accept legacy (pre-uiHost-binding) tokens on.
// Extend this set when a new Cloud region ships — stale toolbar bundles served
// from the CDN will not learn about new regions automatically, so users on a new
// region keep seeing the confirm modal (safe) but any legacy tokens on that region
// would be silently rejected until the toolbar is rebuilt and deployed.
const TRUSTED_POSTHOG_CLOUD_HOSTNAMES = new Set([
    'us.posthog.com',
    'eu.posthog.com',
    'app.posthog.com', // legacy canonical — kept for customers who pinned to it
])

export function isPostHogCloudHost(uiHost: string): boolean {
    try {
        const { protocol, hostname } = new URL(uiHost)
        return protocol === 'https:' && TRUSTED_POSTHOG_CLOUD_HOSTNAMES.has(hostname)
    } catch {
        return false
    }
}

/**
 * Sanitize a uiHost candidate: returns the canonical `origin` (lowercased hostname,
 * no trailing slash, no path/query/hash) when valid, or null when invalid.
 *
 * Rejects:
 * - non-http(s) schemes (javascript:, data:, blob:, //protocol-relative, etc.)
 * - URLs with userinfo like `https://us.posthog.com@evil.com` — these display
 *   misleadingly in confirmation dialogs where a hurried user may skim for "us.posthog.com"
 *
 * Using `.origin` ensures stored-vs-current comparisons are normalization-insensitive
 * (handles trailing slashes, case differences, default ports).
 */
export function canonicalizeUiHost(candidate: string | undefined | null): string | null {
    if (!candidate) {
        return null
    }
    try {
        const parsed = new URL(candidate)
        if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
            return null
        }
        if (parsed.username || parsed.password) {
            return null
        }
        return parsed.origin
    } catch {
        return null
    }
}

/**
 * Sanitize an apiHost candidate. Like canonicalizeUiHost, but preserves the URL
 * path so reverse-proxy deployments (e.g. `https://proxy/ingest`) keep working
 * — apiHost is concatenated with `/static/toolbar.css` and `/i/v1/logs`, so the
 * path prefix must survive. Query and fragment are still dropped.
 */
export function canonicalizeApiHost(candidate: string | undefined | null): string | null {
    if (!candidate) {
        return null
    }
    try {
        const parsed = new URL(candidate)
        if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
            return null
        }
        if (parsed.username || parsed.password) {
            return null
        }
        const pathname = parsed.pathname.replace(/\/+$/, '')
        return parsed.origin + pathname
    } catch {
        return null
    }
}

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
    values: { accessToken: string | null; uiHost: string },
    actions: TokenActions
): void {
    if (values.accessToken || pendingCodeExchange) {
        return
    }
    let parsed: unknown
    try {
        const stored = localStorage.getItem(OAUTH_LOCALSTORAGE_KEY)
        if (!stored) {
            return
        }
        parsed = JSON.parse(stored)
    } catch {
        toolbarLogger.warn('auth', 'Failed to parse stored OAuth tokens from localStorage')
        localStorage.removeItem(OAUTH_LOCALSTORAGE_KEY)
        return
    }
    if (!parsed || typeof parsed !== 'object') {
        localStorage.removeItem(OAUTH_LOCALSTORAGE_KEY)
        return
    }
    const { accessToken, refreshToken, clientId, uiHost: storedUiHost } = parsed as Record<string, unknown>
    // Validate every field is a non-empty string — guards against a third-party script
    // writing garbage (or an older version writing a different shape) that would later
    // blow up on fetch header construction.
    if (
        typeof accessToken !== 'string' ||
        !accessToken ||
        typeof refreshToken !== 'string' ||
        !refreshToken ||
        typeof clientId !== 'string' ||
        !clientId
    ) {
        localStorage.removeItem(OAUTH_LOCALSTORAGE_KEY)
        return
    }
    // Canonicalize both sides so trailing-slash, port, or case differences don't
    // force unnecessary re-auth. values.uiHost already flows through the selector
    // which canonicalizes, but storedUiHost may have been written by an older
    // toolbar version that only trimmed trailing slashes.
    const canonicalStoredUiHost =
        typeof storedUiHost === 'string' && storedUiHost ? canonicalizeUiHost(storedUiHost) : null
    if (canonicalStoredUiHost && canonicalStoredUiHost !== values.uiHost) {
        // Stored tokens were issued for a different PostHog app — an attacker may
        // have injected a malicious uiHost via crafted hash params hoping to receive
        // the token on the next API call. Discard and clean up.
        toolbarLogger.warn('auth', 'Stored OAuth tokens are for a different uiHost, discarding', {
            stored: canonicalStoredUiHost,
            current: values.uiHost,
        })
        toolbarPosthogJS.capture('toolbar oauth tokens discarded', {
            reason: 'uihost_mismatch',
            stored_ui_host: canonicalStoredUiHost,
            current_ui_host: values.uiHost,
        })
        localStorage.removeItem(OAUTH_LOCALSTORAGE_KEY)
        return
    }
    // Legacy tokens (stored before uiHost binding was added) have no storedUiHost.
    // Accept them only when the current uiHost is a trusted PostHog Cloud host —
    // otherwise an attacker-injected uiHost would receive the token on the next API
    // call. Self-hosted users with legacy tokens will need to re-authenticate once,
    // which is the intended trade-off.
    if (!canonicalStoredUiHost && !isPostHogCloudHost(values.uiHost)) {
        toolbarLogger.warn('auth', 'Rejecting legacy OAuth tokens for untrusted uiHost', {
            current: values.uiHost,
        })
        toolbarPosthogJS.capture('toolbar oauth tokens discarded', {
            reason: 'legacy_untrusted_host',
            current_ui_host: values.uiHost,
        })
        localStorage.removeItem(OAUTH_LOCALSTORAGE_KEY)
        return
    }
    actions.setOAuthTokens(accessToken, refreshToken, clientId)
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
    values: {
        isAuthenticated: boolean
        uiHost: string
        apiHost: string
        apiHostResolution: { host: string; source: ApiHostSource }
    }
): void {
    if (props.instrument) {
        toolbarPosthogJS.opt_in_capturing()
        if (props.distinctId) {
            toolbarPosthogJS.identify(props.distinctId, props.userEmail ? { email: props.userEmail } : {})
        }
    }

    const loadStart = (window as any).__posthog_toolbar_load_start as number | undefined
    delete (window as any).__posthog_toolbar_load_start
    const loadDurationMs = loadStart ? Math.round(performance.now() - loadStart) : undefined

    toolbarPosthogJS.capture('toolbar loaded', {
        is_authenticated: values.isAuthenticated,
        source: props.source || 'unknown',
        ui_host: values.uiHost,
        api_host: values.apiHost,
        api_host_source: values.apiHostResolution.source,
        api_host_fallback: values.apiHostResolution.source.startsWith('fallback_'),
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
            restoreOAuthTokens(false, { accessToken: null, uiHost }, actions)
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
    payload?: Record<string, any> | FormData,
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

    const isFormData = typeof FormData !== 'undefined' && payload instanceof FormData
    const buildHeaders = (token: string): Record<string, string> => {
        const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
        // Don't set Content-Type for FormData: the browser supplies it with a
        // multipart boundary. Setting it manually would corrupt the body.
        if (payload && !isFormData) {
            headers['Content-Type'] = 'application/json'
        }
        return headers
    }
    // `withTokenRefresh` may replay the same request once with a new token. We intentionally
    // reuse the same FormData instance here: FormData is re-readable (unlike one-shot streams),
    // so both the initial send and the retry can consume it safely.
    const body: BodyInit | undefined = payload
        ? isFormData
            ? (payload as FormData)
            : JSON.stringify(payload)
        : undefined

    const startTime = performance.now()
    let didRetry = false

    let response = await fetch(fullUrl, {
        method,
        headers: buildHeaders(accessToken),
        ...(body !== undefined ? { body } : {}),
    })

    response = await withTokenRefresh(response, async (newAccessToken) => {
        didRetry = true
        return await fetch(fullUrl, {
            method,
            headers: buildHeaders(newAccessToken),
            ...(body !== undefined ? { body } : {}),
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
    // Fail fast when there's no session to begin with — don't route through
    // toolbarFetch (which would return a stub 401 and trip tokenExpired
    // telemetry / toasts for a user who was never authenticated).
    if (!toolbarConfigLogic.findMounted()?.values.accessToken) {
        throw new Error('Toolbar not authenticated')
    }

    // Route through toolbarFetch so authenticated uploads share the single
    // auth + token-refresh implementation. toolbarFetch sends the bearer to
    // uiHost (validated + token-bound), closing the apiHost-redirect leak.
    const formData = new FormData()
    formData.append('image', file)

    const response = await toolbarFetch('/api/projects/@current/uploaded_media/', 'POST', formData)

    if (response.status === 401) {
        // Session was valid at start but expired and refresh failed.
        toolbarConfigLogic.findMounted()?.actions.tokenExpired()
        throw new Error('Authentication expired')
    }

    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        // toolbarFetch already calls tokenExpired() on 403, so no need to repeat it here.
        throw new Error(errorData.detail || `Upload failed: ${response.status}`)
    }

    const data: ToolbarMediaUploadResponse = await response.json()
    return {
        id: data.id,
        url: data.image_location,
        fileName: data.name,
    }
}
