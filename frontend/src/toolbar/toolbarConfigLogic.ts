import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl, encodeParams } from 'kea-router'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ToolbarProps } from '~/types'

import type { toolbarConfigLogicType } from './toolbarConfigLogicType'
import { LOCALSTORAGE_KEY } from './utils'

export type ToolbarAuthorizationState = Pick<ToolbarProps, 'authorizationCode' | 'accessToken'>

export type ToolbarTokenInfo = {
    id: number
    aud: string
    scopes: string[]
    exp: number
}

export const TOOLBAR_REQUIRED_API_SCOPES = [
    'project:read',
    'action:write',
    'feature_flag:read',
    'heatmaps:read',
    'user:read',
    'experiment:write',
].join(' ')

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
        onAuthenticationError: (message: string) => ({ message }),
        checkAuthorization: true,
    }),

    reducers(({ props }) => ({
        // TRICKY: We cache a copy of the props. This allows us to connect the logic without passing the props in - only the top level caller has to do this.
        props: [props],
        actionId: [props.actionId || null, { logout: () => null, clearUserIntent: () => null }],
        experimentId: [props.experimentId || null, { logout: () => null, clearUserIntent: () => null }],
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

                onAuthenticationError: () => {
                    return {}
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
        dataAttributes: [(s) => [s.props], (props): string[] => props.dataAttributes ?? []],
        accessToken: [(s) => [s.authorization], (authorization) => authorization?.accessToken ?? null],
        // TODO: Check for expiry
        isAuthenticated: [(s) => [s.accessToken], (accessToken) => !!accessToken],

        tokenInfo: [
            (s) => [s.accessToken],
            (accessToken): ToolbarTokenInfo | null => {
                // Loosely parse the jwt info
                if (!accessToken) {
                    return null
                }

                const [_, payload] = accessToken.split('.')
                const decodedPayload = atob(payload)
                const parsedPayload = JSON.parse(decodedPayload)
                return parsedPayload
            },
        ],

        projectId: [(s) => [s.tokenInfo], (tokenInfo): string | number => tokenInfo?.id ?? '@current'],
    }),

    listeners(({ values, actions }) => ({
        authorizeSuccess: async () => {
            // TRICKY: Need to do on the next tick to ensure the loader values are ready
            toolbarPosthogJS.capture('toolbar authenticate', { is_authenticated: values.isAuthenticated })
            const encodedUrl = encodeURIComponent(window.location.href)
            actions.persistConfig()

            const url = `${values.apiURL}/project/${values.posthog?.config.token}/client_authorization/?code=${values.authorization.authorizationCode}&redirect_url=${encodedUrl}&scopes=${TOOLBAR_REQUIRED_API_SCOPES}&client_id=toolbar`

            const popupWidth = 600
            const popupHeight = 700
            const left = (window.screen.width - popupWidth) / 2
            const top = (window.screen.height - popupHeight) / 2

            // open the url in a little popup window
            const popup = window.open(
                url,
                'authPopup',
                `width=${popupWidth},height=${popupHeight},top=${top},left=${left},resizable=yes,scrollbars=yes`
            )
            popup?.focus()

            // TODO: Start timer checking for the authorization to complete
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
                experimentId: values.experimentId ?? undefined,
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
    const projectId = toolbarConfigLogic.findMounted()?.values.projectId

    let fullUrl: string
    if (urlConstruction === 'use-as-provided') {
        fullUrl = url
    } else {
        const { pathname, searchParams } = combineUrl(url)

        const params = { ...searchParams }
        fullUrl = `${apiURL}${pathname.replace('/projects/@current', `/projects/${projectId}`)}${encodeParams(
            params,
            '?'
        )}`
    }

    const response = await fetch(fullUrl, {
        method,
        body: payload ? JSON.stringify(payload) : undefined,
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${accessToken}`,
        },
    })
    // TODO: Change to some sort of indicator that a reauth may be required.
    if (response.status === 403) {
        toolbarConfigLogic.actions.onAuthenticationError('forbidden')
    }
    if (response.status == 401) {
        toolbarConfigLogic.actions.onAuthenticationError('forbidden')
    }
    return response
}
