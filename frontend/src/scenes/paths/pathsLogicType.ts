// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic, BreakPointFunction } from 'kea'

export interface pathsLogicType extends Logic {
    actionCreators: {
        loadPaths: (
            _: any
        ) => {
            type: 'load paths (scenes.paths.pathsLogic)'
            payload: any
        }
        loadPathsSuccess: (paths: {
            nodes: never[]
            links: never[]
        }) => {
            type: 'load paths success (scenes.paths.pathsLogic)'
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
            type: 'load paths failure (scenes.paths.pathsLogic)'
            payload: {
                error: string
            }
        }
        setProperties: (
            properties: any
        ) => {
            type: 'set properties (scenes.paths.pathsLogic)'
            payload: {
                properties: any
            }
        }
        setFilter: (
            filter: any
        ) => {
            type: 'set filter (scenes.paths.pathsLogic)'
            payload: any
        }
    }
    actionKeys: {
        'load paths (scenes.paths.pathsLogic)': 'loadPaths'
        'load paths success (scenes.paths.pathsLogic)': 'loadPathsSuccess'
        'load paths failure (scenes.paths.pathsLogic)': 'loadPathsFailure'
        'set properties (scenes.paths.pathsLogic)': 'setProperties'
        'set filter (scenes.paths.pathsLogic)': 'setFilter'
    }
    actionTypes: {
        loadPaths: 'load paths (scenes.paths.pathsLogic)'
        loadPathsSuccess: 'load paths success (scenes.paths.pathsLogic)'
        loadPathsFailure: 'load paths failure (scenes.paths.pathsLogic)'
        setProperties: 'set properties (scenes.paths.pathsLogic)'
        setFilter: 'set filter (scenes.paths.pathsLogic)'
    }
    actions: {
        loadPaths: (_: any) => void
        loadPathsSuccess: (paths: { nodes: never[]; links: never[] }) => void
        loadPathsFailure: (error: string) => void
        setProperties: (properties: any) => void
        setFilter: (filter: any) => void
    }
    constants: {}
    defaults: {
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
    events: {
        afterMount: () => void
    }
    key: undefined
    listeners: {
        setProperties: ((
            payload: {
                properties: any
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'set properties (scenes.paths.pathsLogic)'
                payload: {
                    properties: any
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        setFilter: ((
            payload: any,
            breakpoint: BreakPointFunction,
            action: {
                type: 'set filter (scenes.paths.pathsLogic)'
                payload: any
            },
            previousState: any
        ) => void | Promise<void>)[]
    }
    path: ['scenes', 'paths', 'pathsLogic']
    pathString: 'scenes.paths.pathsLogic'
    props: Record<string, unknown>
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
    reducerOptions: {}
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
    sharedListeners: {}
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
    _isKeaWithKey: false
    __keaTypeGenInternalSelectorTypes: {
        propertiesForUrl: (arg1: any, arg2: any) => '' | { insight: string }
    }
}
