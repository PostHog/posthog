// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic } from 'kea'

export interface currentPageLogicType extends Logic {
    actionCreators: {
        setHref: (
            href: string
        ) => {
            type: 'set href (toolbar.stats.currentPageLogic)'
            payload: {
                href: string
            }
        }
    }
    actionKeys: {
        'set href (toolbar.stats.currentPageLogic)': 'setHref'
    }
    actionTypes: {
        setHref: 'set href (toolbar.stats.currentPageLogic)'
    }
    actions: {
        setHref: (href: string) => void
    }
    constants: {}
    defaults: {
        href: string
    }
    events: {
        afterMount: () => void
        beforeUnmount: () => void
    }
    key: undefined
    listeners: {}
    path: ['toolbar', 'stats', 'currentPageLogic']
    pathString: 'toolbar.stats.currentPageLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        href: string
    }
    reducerOptions: {}
    reducers: {
        href: (state: string, action: any, fullState: any) => string
    }
    selector: (
        state: any
    ) => {
        href: string
    }
    selectors: {
        href: (state: any, props: any) => string
    }
    sharedListeners: {}
    values: {
        href: string
    }
    _isKea: true
    _isKeaWithKey: false
}
