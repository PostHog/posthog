import { kea } from 'kea'
import { toolbarLogicType } from '~/toolbar/toolbarLogicType'

// input: props = all editorProps
export const toolbarLogic = kea<toolbarLogicType>({
    actions: () => ({
        authenticate: true,
    }),

    reducers: ({ props }) => ({
        rawApiURL: [props.apiURL as string],
        rawJsURL: [(props.jsURL || props.apiURL) as string],
        temporaryToken: [(props.temporaryToken || null) as string | null],
        actionId: [(props.actionId ? parseInt(props.actionId) : null) as number | null],
        userIntent: [(props.userIntent || null) as string | null],
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
        },
    }),
})

