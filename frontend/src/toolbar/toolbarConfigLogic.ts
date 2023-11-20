import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { ToolbarProps } from '~/types'
import { clearSessionToolbarToken } from '~/toolbar/utils'
import { posthog } from '~/toolbar/posthog'
import { lemonToast } from 'lib/lemon-ui/lemonToast'

import type { toolbarConfigLogicType } from './toolbarConfigLogicType'

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
