import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { combineUrl, encodeParams } from 'kea-router'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { posthog } from '~/toolbar/posthog'
import { ToolbarProps } from '~/types'

import type { toolbarConfigLogicType } from './toolbarConfigLogicType'
import { clearSessionToolbarToken } from './utils'

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
    }),

    reducers(({ props }) => ({
        rawApiURL: [props.apiURL as string],
        rawJsURL: [(props.jsURL || props.apiURL) as string],
        temporaryToken: [props.temporaryToken || null, { logout: () => null, tokenExpired: () => null }],
        actionId: [props.actionId || null, { logout: () => null, clearUserIntent: () => null }],
        userIntent: [props.userIntent || null, { logout: () => null, clearUserIntent: () => null }],
        source: [props.source || null, { logout: () => null }],
        buttonVisible: [true, { showButton: () => true, hideButton: () => false, logout: () => false }],
        dataAttributes: [props.dataAttributes || []],
        posthog: [props.posthog ?? null],
    })),

    selectors({
        apiURL: [(s) => [s.rawApiURL], (apiURL) => `${apiURL.endsWith('/') ? apiURL.replace(/\/+$/, '') : apiURL}`],
        jsURL: [
            (s) => [s.rawJsURL, s.apiURL],
            (rawJsURL, apiUrl) =>
                `${rawJsURL ? (rawJsURL.endsWith('/') ? rawJsURL.replace(/\/+$/, '') : rawJsURL) : apiUrl}`,
        ],
        isAuthenticated: [(s) => [s.temporaryToken], (temporaryToken) => !!temporaryToken],
    }),

    listeners(({ values }) => ({
        authenticate: () => {
            posthog.capture('toolbar authenticate', { is_authenticated: values.isAuthenticated })
            const encodedUrl = encodeURIComponent(window.location.href)
            window.location.href = `${values.apiURL}/authorize_and_redirect/?redirect=${encodedUrl}`
            clearSessionToolbarToken()
        },
        logout: () => {
            posthog.capture('toolbar logout')
            clearSessionToolbarToken()
        },
        tokenExpired: () => {
            posthog.capture('toolbar token expired')
            console.warn('PostHog Toolbar API token expired. Clearing session.')
            if (values.source !== 'localstorage') {
                lemonToast.error('PostHog Toolbar API token expired.')
            }
            clearSessionToolbarToken()
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
        // Do not try to authenticate if the user has no project access altogether
        if (responseData.detail !== "You don't have access to the project.") {
            toolbarConfigLogic.actions.authenticate()
        }
    }
    return response
}
