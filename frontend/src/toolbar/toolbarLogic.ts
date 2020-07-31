import { kea } from 'kea'
import { toolbarLogicType } from '~/toolbar/toolbarLogicType'
import { EditorProps } from '~/types'
import { dockLogic } from '~/toolbar/dockLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { toolbarTabLogic } from '~/toolbar/toolbarTabLogic'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'

// input: props = all editorProps
export const toolbarLogic = kea<toolbarLogicType>({
    props: {} as EditorProps,

    actions: () => ({
        authenticate: true,
        processUserIntent: true,
        clearUserIntent: true,
    }),

    reducers: ({ props }: { props: EditorProps }) => ({
        rawApiURL: [props.apiURL as string],
        rawJsURL: [(props.jsURL || props.apiURL) as string],
        temporaryToken: [props.temporaryToken || null],
        actionId: [props.actionId || null, { clearUserIntent: () => null }],
        userIntent: [props.userIntent || null, { clearUserIntent: () => null }],
    }),

    selectors: ({ selectors }) => ({
        apiURL: [() => [selectors.rawApiURL], (apiURL) => `${apiURL}${apiURL.endsWith('/') ? '' : '/'}`],
        jsURL: [() => [selectors.rawJsURL], (jsURL) => `${jsURL}${jsURL.endsWith('/') ? '' : '/'}`],
        isAuthenticated: [() => [selectors.temporaryToken], (temporaryToken) => !!temporaryToken],
    }),

    listeners: ({ values, props, actions }) => ({
        authenticate: () => {
            const encodedUrl = encodeURIComponent(window.location.href)
            window.location.href = `${values.apiURL}authorize_and_redirect/?redirect=${encodedUrl}`
        },
        processUserIntent: async () => {
            if (props.userIntent === 'add-action' || props.userIntent === 'edit-action') {
                const { mode } = dockLogic.values

                if (mode === '') {
                    dockLogic.actions.setMode('button')
                }

                if (mode === '' || mode === 'button') {
                    actionsTabLogic.actions.showButtonActions()
                    toolbarButtonLogic.actions.showActionsInfo()
                } else if (mode === 'dock') {
                    toolbarTabLogic.actions.setTab('actions')
                }

                if (props.userIntent === 'add-action') {
                    actionsTabLogic.actions.newAction()
                    actions.clearUserIntent()
                }

                if (props.userIntent === 'edit-action') {
                    if (actionsLogic.values.allActions.length > 0) {
                        actionsTabLogic.actions.selectAction(props.actionId)
                        actions.clearUserIntent()
                    } else {
                        // listen to getActionsSuccess in actionsTabLogic
                    }
                }
            }
        },
    }),

    events: ({ actions }) => ({
        afterMount() {
            actions.processUserIntent()
        },
    }),
})
