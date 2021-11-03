import { kea } from 'kea'
import { toolbarLogicType } from './toolbarLogicType'
import { ToolbarProps } from '~/types'
import { clearSessionToolbarToken } from '~/toolbar/utils'
import { posthog } from '~/toolbar/posthog'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { PostHog } from 'posthog-js'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'

// input: props = all editorProps
export const toolbarLogic = kea<toolbarLogicType>({
    props: {} as ToolbarProps,
    connect: () => [
        featureFlagsLogic, // makes an API call that invalidates the token on error
    ],

    actions: () => ({
        authenticate: true,
        logout: true,
        tokenExpired: true,
        processUserIntent: true,
        clearUserIntent: true,
        showButton: true,
        hideButton: true,
    }),

    reducers: ({ props }) => ({
        rawApiURL: [props.apiURL as string],
        rawJsURL: [(props.jsURL || props.apiURL) as string],
        temporaryToken: [props.temporaryToken || null, { logout: () => null, tokenExpired: () => null }],
        actionId: [props.actionId || null, { logout: () => null, clearUserIntent: () => null }],
        userIntent: [props.userIntent || null, { logout: () => null, clearUserIntent: () => null }],
        buttonVisible: [true, { showButton: () => true, hideButton: () => false, logout: () => false }],
        dataAttributes: [(props.dataAttributes || []) as string[]],
        posthog: [(props.posthog ?? null) as PostHog | null],
    }),

    selectors: ({ selectors }) => ({
        apiURL: [
            () => [selectors.rawApiURL],
            (apiURL) => `${apiURL.endsWith('/') ? apiURL.replace(/\/+$/, '') : apiURL}`,
        ],
        jsURL: [() => [selectors.rawJsURL], (jsURL) => `${jsURL.endsWith('/') ? jsURL.replace(/\/+$/, '') : jsURL}`],
        isAuthenticated: [() => [selectors.temporaryToken], (temporaryToken) => !!temporaryToken],
    }),

    listeners: ({ values, props }) => ({
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
            console.log('PostHog Toolbar API token expired. Clearing session.')
            clearSessionToolbarToken()
        },
        processUserIntent: async () => {
            if (props.userIntent === 'add-action' || props.userIntent === 'edit-action') {
                actionsTabLogic.actions.showButtonActions()
                toolbarButtonLogic.actions.showActionsInfo()
                // the right view will next be opened in `actionsTabLogic` on `getActionsSuccess`
            }
        },
    }),

    events: ({ props, actions, values }) => ({
        async afterMount() {
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
        },
    }),
})
