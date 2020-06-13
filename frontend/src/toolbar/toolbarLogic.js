import { kea } from 'kea'

// input: props = all editorProps
export const toolbarLogic = kea({
    actions: () => ({
        authenticate: true,
    }),

    reducers: ({ props }) => ({
        apiURL: [props.apiURL],
        jsURL: [props.jsURL || props.apiURL],
        temporaryToken: [props.temporaryToken || null],
        actionId: [props.actionId || null],
        defaultTab: [props.defaultTab || null],
    }),

    selectors: ({ selectors }) => ({
        isAuthenticated: [() => [selectors.temporaryToken], temporaryToken => !!temporaryToken],
    }),

    listeners: ({ values }) => ({
        authenticate: () => {
            window.location.href = `${values.apiURL}${
                values.apiURL.endsWith('/') ? '' : '/'
            }authorize_and_redirect/?redirect=${encodeURIComponent(window.location.href)}`
        },
    }),
})
