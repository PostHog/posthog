// Auto-generated with kea-typegen. DO NOT EDIT!

export interface currentPageLogicType {
    key: any
    actionCreators: {
        setHref: (
            href: string
        ) => {
            type: 'set href (frontend.src.toolbar.stats.currentPageLogic)'
            payload: { href: string }
        }
    }
    actionKeys: {
        'set href (frontend.src.toolbar.stats.currentPageLogic)': 'setHref'
    }
    actionTypes: {
        setHref: 'set href (frontend.src.toolbar.stats.currentPageLogic)'
    }
    actions: {
        setHref: (href: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'toolbar', 'stats', 'currentPageLogic']
    pathString: 'frontend.src.toolbar.stats.currentPageLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        href: string
    }
    reducerOptions: any
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
    values: {
        href: string
    }
    _isKea: true
}
