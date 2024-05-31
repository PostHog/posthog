import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl, encodeParams } from 'kea-router'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ToolbarProps } from '~/types'

import type { toolbarConfigLogicType } from './toolbarConfigLogicType'
import { LOCALSTORAGE_KEY } from './utils'

export type ToolbarAuthorizationState = Pick<ToolbarProps, 'authorizationCode' | 'accessToken'>

export const toolbarConfigLogic = kea<toolbarConfigLogicType>([
    path(['toolbar', 'toolbarConfigLogic']),
    props({} as ToolbarProps),

    actions({
        logout: true,
        tokenExpired: true,
        clearUserIntent: true,
        showButton: true,
        hideButton: true,
        persistConfig: true,
        authorize: true,
        onAuthenticationErrror: (message: string) => ({ message }),
        checkAuthorization: true,
    }),

    reducers(({ props }) => ({
        // TRICKY: We cache a copy of the props. This allows us to connect the logic without passing the props in - only the top level caller has to do this.
        props: [props],
        actionId: [props.actionId || null, { logout: () => null, clearUserIntent: () => null }],
        userIntent: [props.userIntent || null, { logout: () => null, clearUserIntent: () => null }],
        buttonVisible: [true, { showButton: () => true, hideButton: () => false, logout: () => false }],
    })),

    loaders(({ values, props }) => ({
        authorization: [
            {
                authorizationCode: props.authorizationCode || null,
                accessToken: props.accessToken || null,
            } as ToolbarAuthorizationState,
            {
                authorize: async () => {
                    toolbarPosthogJS.capture('toolbar authenticate', {
                        is_authenticated: values.isAuthenticated,
                    })

                    // TODO: Error handling
                    const res = await toolbarFetch(`/api/client_authorization/start`, 'POST')

                    if (res.status !== 200) {
                        lemonToast.error('Failed to authorize:', await res.json())
                        throw new Error('Failed to authorize')
                    }

                    const payload = await res.json()

                    return {
                        authorizationCode: payload.code,
                    }
                },
                checkAuthorization: async () => {
                    const { authorizationCode } = values.authorization

                    if (!authorizationCode) {
                        return values.authorization
                    }
                    const res = await toolbarFetch(`/api/client_authorization/check?code=${authorizationCode}`)
                    if (res.status !== 200) {
                        throw new Error('Something went wrong. Please re-authenticate')
                    }
                    const payload = await res.json()

                    if (payload.status !== 'authorized') {
                        return values.authorization
                    }

                    return {
                        accessToken: payload.access_token,
                    }
                },

                onAuthenticationErrror: () => {
                    return {
                        accessToken: null,
                        authorizationCode: null,
                    }
                },
            },
        ],
    })),

    selectors({
        posthog: [(s) => [s.props], (props) => props.posthog ?? null],
        apiURL: [
            (s) => [s.props],
            (props: ToolbarProps) => `${props.apiURL?.endsWith('/') ? props.apiURL.replace(/\/+$/, '') : props.apiURL}`,
        ],
        jsURL: [
            (s) => [s.props, s.apiURL],
            (props: ToolbarProps, apiUrl) =>
                `${props.jsURL ? (props.jsURL.endsWith('/') ? props.jsURL.replace(/\/+$/, '') : props.jsURL) : apiUrl}`,
        ],
        dataAttributes: [(s) => [s.props], (props): string[] => props.dataAttributes ?? []],
        accessToken: [(s) => [s.authorization], (authorization) => authorization?.accessToken ?? null],
        // TODO: Check for expiry
        isAuthenticated: [(s) => [s.accessToken], (accessToken) => !!accessToken],
    }),

    listeners(({ values, actions }) => ({
        authorizeSuccess: async () => {
            // TRICKY: Need to do on the next tick to ensure the loader values are ready
            toolbarPosthogJS.capture('toolbar authenticate', { is_authenticated: values.isAuthenticated })
            const encodedUrl = encodeURIComponent(window.location.href)
            actions.persistConfig()
            window.location.href = `${values.apiURL}/client_authorization/?code=${values.authorization.authorizationCode}&redirect_url=${encodedUrl}&client_id=toolbar`
        },

        checkAuthorizationSuccess: () => {
            actions.persistConfig()
        },

        logout: () => {
            toolbarPosthogJS.capture('toolbar logout')
            localStorage.removeItem(LOCALSTORAGE_KEY)
        },
        auth: () => {
            toolbarPosthogJS.capture('toolbar token expired')
            console.warn('PostHog Toolbar API token expired. Clearing session.')
            if (values.props.source !== 'localstorage') {
                lemonToast.error('PostHog Toolbar API token expired.')
            }
            actions.persistConfig()
        },

        persistConfig: () => {
            // Most params we don't change, only those that we may have modified during the session
            const toolbarParams: ToolbarProps = {
                ...values.props,
                actionId: values.actionId ?? undefined,
                userIntent: values.userIntent ?? undefined,
                posthog: undefined,
                featureFlags: undefined,
                accessToken: values.authorization?.accessToken ?? undefined,
                authorizationCode: values.authorization?.authorizationCode ?? undefined,
            }

            localStorage.setItem(LOCALSTORAGE_KEY, JSON.stringify(toolbarParams))
        },
    })),

    afterMount(({ props, values, actions }) => {
        if (props.instrument) {
            const distinctId = props.distinctId

            void toolbarPosthogJS.optIn()

            if (distinctId) {
                toolbarPosthogJS.identify(distinctId, props.userEmail ? { email: props.userEmail } : {})
            }
        }

        if (values.authorization.authorizationCode) {
            actions.checkAuthorization()
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
    const accessToken = toolbarConfigLogic.findMounted()?.values.accessToken
    const apiURL = toolbarConfigLogic.findMounted()?.values.apiURL

    let fullUrl: string
    if (urlConstruction === 'use-as-provided') {
        fullUrl = url
    } else {
        const { pathname, searchParams } = combineUrl(url)
        const params = { ...searchParams }
        fullUrl = `${apiURL}${pathname}${encodeParams(params, '?')}`
    }

    const response = await fetch(fullUrl, {
        method,
        body: payload ? JSON.stringify(payload) : undefined,
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${accessToken}`,
        },
    })
    if (response.status === 403) {
        toolbarConfigLogic.actions.onAuthenticationErrror('forbidden')
    }
    if (response.status == 401) {
        toolbarConfigLogic.actions.onAuthenticationErrror('forbidden')
    }
    return response
}
