import { actions, afterMount, beforeUnmount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { combineUrl, encodeParams } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ToolbarProps } from '~/types'

import type { toolbarConfigLogicType } from './toolbarConfigLogicType'
import { LOCALSTORAGE_KEY } from './utils'

// Singleton refresh promise to prevent concurrent refresh races
let refreshPromise: Promise<{ access_token: string; refresh_token: string; expires_in: number }> | null = null

export const toolbarConfigLogic = kea<toolbarConfigLogicType>([
    path(['toolbar', 'toolbarConfigLogic']),
    props({} as ToolbarProps),

    actions({
        authenticate: true,
        logout: true,
        tokenExpired: true,
        clearUserIntent: true,
        showButton: true,
        hideButton: true,
        persistConfig: true,
        setOAuthTokens: (accessToken: string, refreshToken: string, expiresIn: number, clientId: string) => ({
            accessToken,
            refreshToken,
            expiresIn,
            clientId,
        }),
    }),

    reducers(({ props }) => ({
        // TRICKY: We cache a copy of the props. This allows us to connect the logic without passing the props in - only the top level caller has to do this.
        props: [props],
        temporaryToken: [
            props.temporaryToken || null,
            { logout: () => null, tokenExpired: () => null, authenticate: () => null },
        ],
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
    })),

    selectors({
        posthog: [(s) => [s.props], (props) => props.posthog ?? null],
        // UI host for navigation links (actions, feature flags, experiments, etc.) and API requests
        // Uses posthog.config.ui_host if available, otherwise falls back to props.apiURL for backwards compatibility
        uiHost: [
            (s) => [s.props],
            (props: ToolbarProps): string => {
                if (props.posthog?.config?.ui_host) {
                    return props.posthog.config.ui_host.replace(/\/+$/, '')
                }

                // Fallback: if apiURL prop is set, use it (backwards compatibility)
                if (props.apiURL) {
                    return props.apiURL.replace(/\/+$/, '')
                }

                // Final fallback: current origin
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
        isAuthenticated: [
            (s) => [s.temporaryToken, s.accessToken],
            (temporaryToken, accessToken) => !!temporaryToken || !!accessToken,
        ],
        toolbarFlagsKey: [(s) => [s.props], (props): string | undefined => props.toolbarFlagsKey],
    }),

    listeners(({ values, actions }) => ({
        authenticate: () => {
            toolbarPosthogJS.capture('toolbar authenticate', { is_authenticated: values.isAuthenticated })
            const encodedUrl = encodeURIComponent(window.location.href)
            actions.persistConfig()

            if (values.temporaryToken) {
                // Legacy flow: full-page redirect
                window.location.href = `${values.uiHost}/authorize_and_redirect/?redirect=${encodedUrl}`
            } else {
                // OAuth flow: popup window
                const authUrl = `${values.uiHost}/toolbar_oauth/authorize/?redirect=${encodedUrl}`
                window.open(authUrl, 'posthog_toolbar_oauth', 'width=600,height=700')
            }
        },
        logout: () => {
            toolbarPosthogJS.capture('toolbar logout')
            localStorage.removeItem(LOCALSTORAGE_KEY)
        },
        tokenExpired: () => {
            toolbarPosthogJS.capture('toolbar token expired')
            console.warn('PostHog Toolbar API token expired. Clearing session.')
            if (values.props.source !== 'localstorage') {
                lemonToast.error('PostHog Toolbar API token expired.')
            }
            actions.persistConfig()
        },
        setOAuthTokens: () => {
            actions.persistConfig()
        },
        persistConfig: () => {
            // Most params we don't change, only those that we may have modified during the session
            const toolbarParams: ToolbarProps = {
                ...values.props,
                temporaryToken: values.temporaryToken ?? undefined,
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
        },
    })),

    afterMount(({ props, values, actions, cache }) => {
        if (props.instrument) {
            const distinctId = props.distinctId

            toolbarPosthogJS.opt_in_capturing()

            if (distinctId) {
                toolbarPosthogJS.identify(distinctId, props.userEmail ? { email: props.userEmail } : {})
            }
        }

        toolbarPosthogJS.capture('toolbar loaded', { is_authenticated: values.isAuthenticated })

        // Listen for OAuth callback postMessage from the popup
        cache.oauthMessageHandler = (event: MessageEvent): void => {
            if (event.origin !== values.uiHost) {
                return
            }
            if (event.data?.type !== 'toolbar_oauth_callback') {
                return
            }
            if (event.data.error) {
                console.error('PostHog Toolbar OAuth error:', event.data.error, event.data.error_description)
                return
            }
            if (event.data.access_token) {
                actions.setOAuthTokens(
                    event.data.access_token,
                    event.data.refresh_token,
                    event.data.expires_in,
                    event.data.client_id
                )
            }
        }
        window.addEventListener('message', cache.oauthMessageHandler)
    }),

    beforeUnmount(({ cache }) => {
        if (cache.oauthMessageHandler) {
            window.removeEventListener('message', cache.oauthMessageHandler)
        }
    }),
])

async function refreshOAuthTokens(
    uiHost: string,
    clientId: string,
    currentRefreshToken: string
): Promise<{
    access_token: string
    refresh_token: string
    expires_in: number
}> {
    if (refreshPromise) {
        return refreshPromise
    }

    refreshPromise = (async () => {
        try {
            const response = await fetch(`${uiHost}/api/user/toolbar_oauth_refresh/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: currentRefreshToken, client_id: clientId }),
            })

            if (!response.ok) {
                throw new Error(`Refresh failed: ${response.status}`)
            }

            return await response.json()
        } finally {
            refreshPromise = null
        }
    })()

    return refreshPromise
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
    const temporaryToken = logic?.values.temporaryToken
    const accessToken = logic?.values.accessToken
    const refreshToken = logic?.values.refreshToken
    const clientId = logic?.values.clientId
    const host = logic?.values.uiHost

    const useBearer = !!accessToken

    let fullUrl: string
    if (urlConstruction === 'use-as-provided') {
        fullUrl = url
    } else {
        const { pathname, searchParams } = combineUrl(url)
        if (useBearer) {
            fullUrl = `${host}${pathname}${encodeParams(searchParams, '?')}`
        } else {
            const params = { ...searchParams, temporary_token: temporaryToken }
            fullUrl = `${host}${pathname}${encodeParams(params, '?')}`
        }
    }

    const headers: Record<string, string> = {}
    if (useBearer) {
        headers['Authorization'] = `Bearer ${accessToken}`
    }
    if (payload) {
        headers['Content-Type'] = 'application/json'
    }

    const response = await fetch(fullUrl, {
        method,
        headers,
        ...(payload ? { body: JSON.stringify(payload) } : {}),
    })

    if (response.status === 401 && useBearer && refreshToken && clientId && host) {
        // Attempt token refresh
        try {
            const tokens = await refreshOAuthTokens(host, clientId, refreshToken)
            toolbarConfigLogic.actions.setOAuthTokens(
                tokens.access_token,
                tokens.refresh_token,
                tokens.expires_in,
                clientId
            )

            // Retry with new token
            const retryHeaders: Record<string, string> = { Authorization: `Bearer ${tokens.access_token}` }
            if (payload) {
                retryHeaders['Content-Type'] = 'application/json'
            }
            return await fetch(fullUrl, {
                method,
                headers: retryHeaders,
                ...(payload ? { body: JSON.stringify(payload) } : {}),
            })
        } catch {
            toolbarConfigLogic.actions.tokenExpired()
            return response
        }
    }

    if (response.status === 403) {
        const responseData = await response.json()
        if (responseData.detail === "You don't have access to the project.") {
            toolbarConfigLogic.actions.authenticate()
        }
    }
    if (response.status === 401) {
        toolbarConfigLogic.actions.tokenExpired()
    }
    return response
}

export interface ToolbarMediaUploadResponse {
    id: string
    image_location: string
    name: string
}

/**
 * Upload media (images) from the toolbar.
 * Supports both temporary token (query param) and OAuth Bearer token auth.
 */
export async function toolbarUploadMedia(file: File): Promise<{ id: string; url: string; fileName: string }> {
    const logic = toolbarConfigLogic.findMounted()
    const temporaryToken = logic?.values.temporaryToken
    const accessToken = logic?.values.accessToken
    const refreshToken = logic?.values.refreshToken
    const clientId = logic?.values.clientId
    const apiHost = logic?.values.apiHost
    const uiHost = logic?.values.uiHost

    if ((!temporaryToken && !accessToken) || !apiHost) {
        throw new Error('Toolbar not authenticated')
    }

    const formData = new FormData()
    formData.append('image', file)

    const useBearer = !!accessToken
    let url: string
    const headers: Record<string, string> = {}

    if (useBearer) {
        url = `${apiHost}/api/projects/@current/uploaded_media/`
        headers['Authorization'] = `Bearer ${accessToken}`
    } else {
        url = `${apiHost}/api/projects/@current/uploaded_media/${encodeParams({ temporary_token: temporaryToken }, '?')}`
    }

    let response = await fetch(url, { method: 'POST', body: formData, headers })

    if (response.status === 401 && useBearer && refreshToken && clientId && uiHost) {
        try {
            const tokens = await refreshOAuthTokens(uiHost, clientId, refreshToken)
            toolbarConfigLogic.actions.setOAuthTokens(
                tokens.access_token,
                tokens.refresh_token,
                tokens.expires_in,
                clientId
            )
            response = await fetch(url, {
                method: 'POST',
                body: formData,
                headers: { Authorization: `Bearer ${tokens.access_token}` },
            })
        } catch {
            toolbarConfigLogic.actions.tokenExpired()
            throw new Error('Authentication expired')
        }
    }

    if (response.status === 401) {
        toolbarConfigLogic.actions.tokenExpired()
        throw new Error('Authentication expired')
    }

    if (response.status === 403) {
        const responseData = await response.json()
        if (responseData.detail === "You don't have access to the project.") {
            toolbarConfigLogic.actions.authenticate()
        }
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
