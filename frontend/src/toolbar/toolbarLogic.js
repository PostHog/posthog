import { kea } from 'kea'

// input: props = all editorProps
export const toolbarLogic = kea({
    actions: () => ({
        authenticate: true,
    }),

    reducers: ({ props }) => ({
        rawApiURL: [props.apiURL],
        rawJsURL: [props.jsURL || props.apiURL],
        temporaryToken: [props.temporaryToken || null],
        actionId: [props.actionId || null],
        userIntent: [props.userIntent || null],
    }),

    selectors: ({ selectors }) => ({
        apiURL: [() => [selectors.rawApiURL], apiURL => `${apiURL}${apiURL.endsWith('/') ? '' : '/'}`],
        jsURL: [() => [selectors.rawJsURL], jsURL => `${jsURL}${jsURL.endsWith('/') ? '' : '/'}`],
        isAuthenticated: [() => [selectors.temporaryToken], temporaryToken => !!temporaryToken],
    }),

    listeners: ({ values }) => ({
        authenticate: () => {
            const encodedUrl = encodeURIComponent(window.location.href)
            window.location.href = `${values.apiURL}authorize_and_redirect/?redirect=${encodedUrl}`
        },
    }),
})
