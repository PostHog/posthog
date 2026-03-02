import { actions, afterMount, beforeUnmount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { combineUrl, encodeParams } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ToolbarProps } from '~/types'

import { withTokenRefresh } from './toolbarAuth'
import type { toolbarConfigLogicType } from './toolbarConfigLogicType'
import { LOCALSTORAGE_KEY, OAUTH_LOCALSTORAGE_KEY } from './utils'

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
        setOAuthTokens: (accessToken: string, refreshToken: string, clientId: string) => ({
            accessToken,
            refreshToken,
            clientId,
        }),
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
        isAuthenticated: [(s) => [s.accessToken], (accessToken) => !!accessToken],
        toolbarFlagsKey: [(s) => [s.props], (props): string | undefined => props.toolbarFlagsKey],
    }),

    listeners(({ values, actions }) => ({
        authenticate: () => {
            toolbarPosthogJS.capture('toolbar authenticate', { is_authenticated: values.isAuthenticated })
            const encodedUrl = encodeURIComponent(window.location.href)
            actions.persistConfig()

            const authUrl = `${values.uiHost}/toolbar_oauth/authorize/?redirect=${encodedUrl}`
            const popup = window.open(authUrl, 'posthog_toolbar_oauth', 'width=600,height=700')
            if (!popup) {
                lemonToast.error('Popup was blocked. Please allow popups for this site to authenticate.')
            }
        },
        logout: () => {
            toolbarPosthogJS.capture('toolbar logout')
            localStorage.removeItem(LOCALSTORAGE_KEY)
            localStorage.removeItem(OAUTH_LOCALSTORAGE_KEY)
        },
        tokenExpired: () => {
            toolbarPosthogJS.capture('toolbar token expired')
            console.warn('PostHog Toolbar session expired. Clearing session.')
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
        // Always try to restore OAuth tokens from separate storage.
        // posthog-js overwrites LOCALSTORAGE_KEY with hash params on each launch,
        // losing the OAuth tokens. This separate key survives that overwrite.
        if (!values.accessToken) {
            try {
                const stored = localStorage.getItem(OAUTH_LOCALSTORAGE_KEY)
                if (stored) {
                    const { accessToken, refreshToken, clientId } = JSON.parse(stored)
                    if (accessToken && refreshToken && clientId) {
                        actions.setOAuthTokens(accessToken, refreshToken, clientId)
                    }
                }
            } catch {
                // ignore localStorage errors
            }
        }

        // Migrate users from the old temporaryToken flow to OAuth.
        if (!values.accessToken && props.temporaryToken) {
            actions.tokenExpired()
        }

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
            if (event.data.access_token && event.data.refresh_token && event.data.client_id) {
                actions.setOAuthTokens(event.data.access_token, event.data.refresh_token, event.data.client_id)
            } else if (event.data.access_token) {
                console.error('PostHog Toolbar OAuth: incomplete token payload')
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

    let response = await fetch(fullUrl, {
        method,
        headers,
        ...(payload ? { body: JSON.stringify(payload) } : {}),
    })

    response = await withTokenRefresh(response, async (newAccessToken) => {
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

    if (response.status === 403) {
        const responseData = await response.clone().json()
        if (responseData.detail === "You don't have access to the project.") {
            toolbarConfigLogic.actions.authenticate()
        }
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
