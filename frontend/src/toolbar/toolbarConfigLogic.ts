import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { combineUrl, encodeParams } from 'kea-router'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { posthog } from '~/toolbar/posthog'
import { ToolbarParams, ToolbarProps } from '~/types'

import type { toolbarConfigLogicType } from './toolbarConfigLogicType'
import { LOCALSTORAGE_KEY } from './utils'

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
        temporaryToken: [
            props.temporaryToken || null,
            { logout: () => null, tokenExpired: () => null, authenticate: () => null },
        ],
        actionId: [props.actionId || null, { logout: () => null, clearUserIntent: () => null }],
        userIntent: [props.userIntent || null, { logout: () => null, clearUserIntent: () => null }],
        buttonVisible: [true, { showButton: () => true, hideButton: () => false, logout: () => false }],
        posthog: [props.posthog ?? null],
    })),

    selectors({
        apiURL: [
            () => [(_, props) => props],
            (props) => `${props.apiURL.endsWith('/') ? props.apiURL.replace(/\/+$/, '') : props.apiURL}`,
        ],
        jsURL: [
            (s) => [(_, props) => props, s.apiURL],
            (props, apiUrl) =>
                `${props.jsURL ? (props.jsURL.endsWith('/') ? props.jsURL.replace(/\/+$/, '') : props.jsURL) : apiUrl}`,
        ],
        dataAttributes: [() => [(_, props) => props], (props): string[] => props.dataAttributes ?? []],
        isAuthenticated: [(s) => [s.temporaryToken], (temporaryToken) => !!temporaryToken],
    }),

    listeners(({ props, values, actions }) => ({
        authenticate: () => {
            posthog.capture('toolbar authenticate', { is_authenticated: values.isAuthenticated })
            const encodedUrl = encodeURIComponent(window.location.href)
            actions.persistConfig()
            window.location.href = `${values.apiURL}/authorize_and_redirect/?redirect=${encodedUrl}`
        },
        logout: () => {
            posthog.capture('toolbar logout')
            localStorage.removeItem(LOCALSTORAGE_KEY)
        },
        tokenExpired: () => {
            posthog.capture('toolbar token expired')
            console.warn('PostHog Toolbar API token expired. Clearing session.')
            if (props.source !== 'localstorage') {
                lemonToast.error('PostHog Toolbar API token expired.')
            }
            actions.persistConfig()
        },

        persistConfig: () => {
            // Most params we don't change, only those that we may have modified during the session
            const toolbarParams: ToolbarProps = {
                ...props,
                temporaryToken: values.temporaryToken ?? undefined,
                actionId: values.actionId ?? undefined,
                userIntent: values.userIntent ?? undefined,
                posthog: undefined,
                featureFlags: undefined,
            }

            localStorage.setItem(LOCALSTORAGE_KEY, JSON.stringify(toolbarParams))
        },
    })),

    afterMount(({ props, values }) => {
        if (props.instrument) {
            const distinctId = props.distinctId
            if (distinctId) {
                posthog.identify(distinctId, props.userEmail ? { email: props.userEmail } : {})
            }
            posthog.optIn()
        }
        posthog.capture('toolbar loaded', { is_authenticated: values.isAuthenticated })
    }),
])

export async function toolbarFetch(
    url: string,
    method: string = 'GET',
    payload?: Record<string, any>,
    /*
     allows caller to control how the provided URL is altered before use
     if "full" then the payload and URL are taken apart and reconstructed
     if "only-add-token" the URL is unchanged, the payload is not used
     but the temporary token is added to the URL
     if "use-as-provided" then the URL is used as-is, and the payload is not used
     this is because the heatmapLogic needs more control over how the query parameters are constructed
    */
    urlConstruction: 'full' | 'only-add-token' | 'use-as-provided' = 'full'
): Promise<Response> {
    const temporaryToken = toolbarConfigLogic.findMounted()?.values.temporaryToken
    const apiURL = toolbarConfigLogic.findMounted()?.values.apiURL

    let fullUrl: string
    if (urlConstruction === 'use-as-provided') {
        fullUrl = url
    } else if (urlConstruction === 'only-add-token') {
        fullUrl = `${url}&temporary_token=${temporaryToken}`
    } else {
        const { pathname, searchParams } = combineUrl(url)
        const params = { ...searchParams, temporary_token: temporaryToken }
        fullUrl = `${apiURL}${pathname}${encodeParams(params, '?')}`
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
