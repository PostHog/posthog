import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { combineUrl, encodeParams } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ToolbarProps } from '~/types'

import type { toolbarConfigLogicType } from './toolbarConfigLogicType'
import { LOCALSTORAGE_KEY } from './utils'

/**
 * Derives the UI host from an API host URL.
 * For PostHog cloud instances, maps API hosts (e.g., us.i.posthog.com) to UI hosts (e.g., us.posthog.com).
 * Returns null if no mapping is found.
 */
function deriveUiHostFromApiHost(apiHost: string | undefined): string | null {
    if (!apiHost) {
        return null
    }

    // Map known PostHog API hosts to their UI counterparts
    const apiToUiMap: Record<string, string> = {
        'https://us.i.posthog.com': 'https://us.posthog.com',
        'https://eu.i.posthog.com': 'https://eu.posthog.com',
        // Also handle without protocol for flexibility
        'us.i.posthog.com': 'https://us.posthog.com',
        'eu.i.posthog.com': 'https://eu.posthog.com',
    }

    const normalizedApiHost = apiHost.replace(/\/+$/, '').toLowerCase()
    return apiToUiMap[normalizedApiHost] ?? null
}

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
    }),

    reducers(({ props }) => ({
        // TRICKY: We cache a copy of the props. This allows us to connect the logic without passing the props in - only the top level caller has to do this.
        props: [props],
        temporaryToken: [
            props.temporaryToken || null,
            { logout: () => null, tokenExpired: () => null, authenticate: () => null },
        ],
        actionId: [props.actionId || null, { logout: () => null, clearUserIntent: () => null }],
        experimentId: [props.experimentId || null, { logout: () => null, clearUserIntent: () => null }],
        productTourId: [props.productTourId || null, { logout: () => null, clearUserIntent: () => null }],
        userIntent: [props.userIntent || null, { logout: () => null, clearUserIntent: () => null }],
        buttonVisible: [true, { showButton: () => true, hideButton: () => false, logout: () => false }],
    })),

    selectors({
        posthog: [(s) => [s.props], (props) => props.posthog ?? null],
        // UI host for navigation links (actions, feature flags, experiments, etc.) and auth redirects
        // Priority order:
        // 1. posthog.config.ui_host (if posthog instance is available and ui_host is set)
        // 2. Saved uiHost from props (persisted to localStorage)
        // 3. Derived from posthog.config.api_host (for known PostHog cloud instances)
        // 4. Derived from props.apiURL (for known PostHog cloud instances)
        // 5. props.apiURL (backwards compatibility, may be incorrect for auth redirects)
        // 6. window.location.origin (final fallback)
        uiHost: [
            (s) => [s.props],
            (props: ToolbarProps): string => {
                // 1. First choice: explicitly configured ui_host from posthog instance
                if (props.posthog?.config?.ui_host) {
                    return props.posthog.config.ui_host.replace(/\/+$/, '')
                }

                // 2. Check for saved uiHost in props (persisted to localStorage)
                if ((props as any).__persistedUiHost) {
                    return (props as any).__persistedUiHost
                }

                // 3. Try to derive UI host from API host (for known PostHog cloud instances)
                const derivedFromApiHost = deriveUiHostFromApiHost(props.posthog?.config?.api_host)
                if (derivedFromApiHost) {
                    return derivedFromApiHost
                }

                // 4. Try to derive from apiURL prop (for known PostHog cloud instances)
                const derivedFromApiUrl = deriveUiHostFromApiHost(props.apiURL)
                if (derivedFromApiUrl) {
                    return derivedFromApiUrl
                }

                // 5. Fallback: if apiURL prop is set, use it (backwards compatibility)
                // Note: This may not be correct for auth redirects if apiURL is an API host
                if (props.apiURL) {
                    return props.apiURL.replace(/\/+$/, '')
                }

                // 6. Final fallback: current origin
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
        isAuthenticated: [(s) => [s.temporaryToken], (temporaryToken) => !!temporaryToken],
        toolbarFlagsKey: [(s) => [s.props], (props): string | undefined => props.toolbarFlagsKey],
    }),

    listeners(({ values, actions }) => ({
        authenticate: () => {
            toolbarPosthogJS.capture('toolbar authenticate', { is_authenticated: values.isAuthenticated })
            const encodedUrl = encodeURIComponent(window.location.href)
            actions.persistConfig()
            // Use UI host for auth redirects (SSO/login)
            window.location.href = `${values.uiHost}/authorize_and_redirect/?redirect=${encodedUrl}`
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

        persistConfig: () => {
            // Most params we don't change, only those that we may have modified during the session
            // We also save the resolved uiHost so authentication works correctly when loaded from localStorage
            const toolbarParams: ToolbarProps & { __persistedUiHost?: string } = {
                ...values.props,
                temporaryToken: values.temporaryToken ?? undefined,
                actionId: values.actionId ?? undefined,
                experimentId: values.experimentId ?? undefined,
                productTourId: values.productTourId ?? undefined,
                userIntent: values.userIntent ?? undefined,
                posthog: undefined,
                // Save the resolved uiHost so it's available when loaded from localStorage
                // This ensures authentication redirects go to the correct PostHog UI
                __persistedUiHost: values.uiHost,
            }

            localStorage.setItem(LOCALSTORAGE_KEY, JSON.stringify(toolbarParams))
        },
    })),

    afterMount(({ props, values }) => {
        if (props.instrument) {
            const distinctId = props.distinctId

            toolbarPosthogJS.opt_in_capturing()

            if (distinctId) {
                toolbarPosthogJS.identify(distinctId, props.userEmail ? { email: props.userEmail } : {})
            }
        }

        toolbarPosthogJS.capture('toolbar loaded', { is_authenticated: values.isAuthenticated })
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
    const temporaryToken = toolbarConfigLogic.findMounted()?.values.temporaryToken
    const host = toolbarConfigLogic.findMounted()?.values.uiHost // Use UI host for API requests since it's pointing to PostHog's UI

    let fullUrl: string
    if (urlConstruction === 'use-as-provided') {
        fullUrl = url
    } else {
        const { pathname, searchParams } = combineUrl(url)
        const params = { ...searchParams, temporary_token: temporaryToken }
        fullUrl = `${host}${pathname}${encodeParams(params, '?')}`
    }

    const payloadData = payload
        ? {
              body: JSON.stringify(payload),
              headers: {
                  'Content-Type': 'application/json',
              },
          }
        : {}

    const response = await fetch(fullUrl, {
        method,
        ...payloadData,
    })
    if (response.status === 403) {
        const responseData = await response.json()
        if (responseData.detail === "You don't have access to the project.") {
            toolbarConfigLogic.actions.authenticate()
        }
    }
    if (response.status == 401) {
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
 * Upload media (images) from the toolbar using temporary token authentication.
 * This is a separate function from toolbarFetch because it needs to handle FormData
 * instead of JSON payloads.
 */
export async function toolbarUploadMedia(file: File): Promise<{ id: string; url: string; fileName: string }> {
    const temporaryToken = toolbarConfigLogic.findMounted()?.values.temporaryToken
    const apiHost = toolbarConfigLogic.findMounted()?.values.apiHost

    if (!temporaryToken || !apiHost) {
        throw new Error('Toolbar not authenticated')
    }

    const formData = new FormData()
    formData.append('image', file)

    const url = `${apiHost}/api/projects/@current/uploaded_media/${encodeParams({ temporary_token: temporaryToken }, '?')}`

    const response = await fetch(url, {
        method: 'POST',
        body: formData,
    })

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
