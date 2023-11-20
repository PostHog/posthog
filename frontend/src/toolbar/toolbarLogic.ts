import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import type { toolbarLogicType } from './toolbarLogicType'
import { ToolbarProps } from '~/types'
import { clearSessionToolbarToken } from '~/toolbar/utils'
import { posthog } from '~/toolbar/posthog'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { lemonToast } from 'lib/lemon-ui/lemonToast'

export const toolbarLogic = kea<toolbarLogicType>([
    path(['toolbar', 'toolbarLogic']),
    props({} as ToolbarProps),

    actions({
        authenticate: true,
        logout: true,
        tokenExpired: true,
        processUserIntent: true,
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

    listeners(({ values, props }) => ({
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
        processUserIntent: () => {
            if (props.userIntent === 'add-action' || props.userIntent === 'edit-action') {
                actionsTabLogic.actions.showButtonActions()
                toolbarButtonLogic.actions.showActionsInfo()
                // the right view will next be opened in `actionsTabLogic` on `getActionsSuccess`
            }
        },
    })),

    afterMount(({ props, actions, values }) => {
        if (props.instrument) {
            const distinctId = props.distinctId
            if (distinctId) {
                posthog.identify(distinctId, props.userEmail ? { email: props.userEmail } : {})
            }
            posthog.optIn()
        }
        if (props.userIntent) {
            actions.processUserIntent()
        }
        posthog.capture('toolbar loaded', { is_authenticated: values.isAuthenticated })
    }),
])
