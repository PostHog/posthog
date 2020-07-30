// Auto-generated with kea-typegen. DO NOT EDIT!

export interface pathsLogicType {
    key: any
    actionCreators: {
        loadPaths: (
            _: any
        ) => {
            type: 'load paths (frontend.src.scenes.paths.pathsLogic)'
            payload: any
        }
        loadPathsSuccess: (paths: {
            nodes: never[]
            links: never[]
        }) => {
            type: 'load paths success (frontend.src.scenes.paths.pathsLogic)'
            payload: {
                paths: {
                    nodes: never[]
                    links: never[]
                }
            }
        }
        loadPathsFailure: (
            error: string
        ) => {
            type: 'load paths failure (frontend.src.scenes.paths.pathsLogic)'
            payload: {
                error: string
            }
        }
        createInsight: (
            filters: Record<string, any>
        ) => {
            type: 'create insight (frontend.src.scenes.paths.pathsLogic)'
            payload: {
                filters: Record<string, any>
            }
        }
        setProperties: (
            properties: any
        ) => {
            type: 'set properties (frontend.src.scenes.paths.pathsLogic)'
            payload: { properties: any }
        }
        setFilter: (
            filter: any
        ) => {
            type: 'set filter (frontend.src.scenes.paths.pathsLogic)'
            payload: any
        }
    }
    actionKeys: {
        'load paths (frontend.src.scenes.paths.pathsLogic)': 'loadPaths'
        'load paths success (frontend.src.scenes.paths.pathsLogic)': 'loadPathsSuccess'
        'load paths failure (frontend.src.scenes.paths.pathsLogic)': 'loadPathsFailure'
        'create insight (frontend.src.scenes.paths.pathsLogic)': 'createInsight'
        'set properties (frontend.src.scenes.paths.pathsLogic)': 'setProperties'
        'set filter (frontend.src.scenes.paths.pathsLogic)': 'setFilter'
    }
    actionTypes: {
        loadPaths: 'load paths (frontend.src.scenes.paths.pathsLogic)'
        loadPathsSuccess: 'load paths success (frontend.src.scenes.paths.pathsLogic)'
        loadPathsFailure: 'load paths failure (frontend.src.scenes.paths.pathsLogic)'
        createInsight: 'create insight (frontend.src.scenes.paths.pathsLogic)'
        setProperties: 'set properties (frontend.src.scenes.paths.pathsLogic)'
        setFilter: 'set filter (frontend.src.scenes.paths.pathsLogic)'
    }
    actions: {
        loadPaths: (_: any) => void
        loadPathsSuccess: (paths: { nodes: never[]; links: never[] }) => void
        loadPathsFailure: (error: string) => void
        createInsight: (filters: Record<string, any>) => void
        setProperties: (properties: any) => void
        setFilter: (filter: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'paths', 'pathsLogic']
    pathString: 'frontend.src.scenes.paths.pathsLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        paths: {
            nodes: never[]
            links: never[]
        }
        pathsLoading: boolean
        initialPathname: (state: any) => any
        filter: {
            type: string
        }
        properties: {}
    }
    reducerOptions: any
    reducers: {
        paths: (
            state: {
                nodes: never[]
                links: never[]
            },
            action: any,
            fullState: any
        ) => {
            nodes: never[]
            links: never[]
        }
        pathsLoading: (state: boolean, action: any, fullState: any) => boolean
        initialPathname: (state: (state: any) => any, action: any, fullState: any) => (state: any) => any
        filter: (
            state: {
                type: string
            },
            action: any,
            fullState: any
        ) => {
            type: string
        }
        properties: (state: {}, action: any, fullState: any) => {}
    }
    selector: (
        state: any
    ) => {
        paths: {
            nodes: never[]
            links: never[]
        }
        pathsLoading: boolean
        initialPathname: (state: any) => any
        filter: {
            type: string
        }
        properties: {}
    }
    selectors: {
        paths: (
            state: any,
            props: any
        ) => {
            nodes: never[]
            links: never[]
        }
        pathsLoading: (state: any, props: any) => boolean
        initialPathname: (state: any, props: any) => (state: any) => any
        filter: (
            state: any,
            props: any
        ) => {
            type: string
        }
        properties: (state: any, props: any) => {}
        propertiesForUrl: (state: any, props: any) => '' | { insight: string }
    }
    values: {
        paths: {
            nodes: never[]
            links: never[]
        }
        pathsLoading: boolean
        initialPathname: (state: any) => any
        filter: {
            type: string
        }
        properties: {}
        propertiesForUrl: '' | { insight: string }
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        propertiesForUrl: (arg1: any, arg2: any) => '' | { insight: string }
    }
}
