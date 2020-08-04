import { kea } from 'kea'
import { toolbarLogicType } from '~/toolbar/toolbarLogicType'
import { EditorProps } from '~/types'
import { clearSessionToolbarToken } from '~/toolbar/utils'
import { posthog } from '~/toolbar/posthog'

// input: props = all editorProps
export const toolbarLogic = kea<toolbarLogicType>({
    props: {} as EditorProps,

    actions: () => ({
        authenticate: true,
        logout: true,
    }),

    reducers: ({ props }: { props: EditorProps }) => ({
        rawApiURL: [props.apiURL as string],
        rawJsURL: [(props.jsURL || props.apiURL) as string],
        temporaryToken: [props.temporaryToken || null, { logout: () => null }],
        actionId: [props.actionId || null, { logout: () => null }],
        userIntent: [props.userIntent || null, { logout: () => null }],
    }),

    selectors: ({ selectors }) => ({
        apiURL: [() => [selectors.rawApiURL], (apiURL) => `${apiURL}${apiURL.endsWith('/') ? '' : '/'}`],
        jsURL: [() => [selectors.rawJsURL], (jsURL) => `${jsURL}${jsURL.endsWith('/') ? '' : '/'}`],
        isAuthenticated: [() => [selectors.temporaryToken], (temporaryToken) => !!temporaryToken],
    }),

    listeners: ({ values }) => ({
        authenticate: () => {
            const encodedUrl = encodeURIComponent(window.location.href)
            window.location.href = `${values.apiURL}authorize_and_redirect/?redirect=${encodedUrl}`
            clearSessionToolbarToken()
        },
        logout: () => {
            clearSessionToolbarToken()
        },
    }),

    events: ({ props }) => ({
        async afterMount() {
            if (props.instrument) {
                posthog.identify(props.distinctId, { email: props.userEmail })
                posthog.optIn()
            }
        },
    }),
})
