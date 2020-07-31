// Auto-generated with kea-typegen. DO NOT EDIT!

export interface sceneLogicType {
    key: undefined
    actionCreators: {
        loadScene: (
            scene: any,
            params: any
        ) => {
            type: 'load scene (scenes.sceneLogic)'
            payload: { scene: any; params: any }
        }
        setScene: (
            scene: any,
            params: any
        ) => {
            type: 'set scene (scenes.sceneLogic)'
            payload: { scene: any; params: any }
        }
        setLoadedScene: (
            scene: any,
            loadedScene: any
        ) => {
            type: 'set loaded scene (scenes.sceneLogic)'
            payload: { scene: any; loadedScene: any }
        }
    }
    actionKeys: {
        'load scene (scenes.sceneLogic)': 'loadScene'
        'set scene (scenes.sceneLogic)': 'setScene'
        'set loaded scene (scenes.sceneLogic)': 'setLoadedScene'
    }
    actionTypes: {
        loadScene: 'load scene (scenes.sceneLogic)'
        setScene: 'set scene (scenes.sceneLogic)'
        setLoadedScene: 'set loaded scene (scenes.sceneLogic)'
    }
    actions: {
        loadScene: (scene: any, params: any) => void
        setScene: (scene: any, params: any) => void
        setLoadedScene: (scene: any, loadedScene: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: {
        scene: null
        params: {}
        loadedScenes: {
            404: {
                component: () => Element
            }
        }
        loadingScene: null
    }
    events: any
    path: ['scenes', 'sceneLogic']
    pathString: 'scenes.sceneLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        scene: null
        params: {}
        loadedScenes: {
            404: {
                component: () => Element
            }
        }
        loadingScene: null
    }
    reducerOptions: any
    reducers: {
        scene: (state: null, action: any, fullState: any) => null
        params: (state: {}, action: any, fullState: any) => {}
        loadedScenes: (
            state: {
                404: {
                    component: () => Element
                }
            },
            action: any,
            fullState: any
        ) => {
            404: {
                component: () => Element
            }
        }
        loadingScene: (state: null, action: any, fullState: any) => null
    }
    selector: (
        state: any
    ) => {
        scene: null
        params: {}
        loadedScenes: {
            404: {
                component: () => Element
            }
        }
        loadingScene: null
    }
    selectors: {
        scene: (state: any, props: any) => null
        params: (state: any, props: any) => {}
        loadedScenes: (
            state: any,
            props: any
        ) => {
            404: {
                component: () => Element
            }
        }
        loadingScene: (state: any, props: any) => null
    }
    values: {
        scene: null
        params: {}
        loadedScenes: {
            404: {
                component: () => Element
            }
        }
        loadingScene: null
    }
    _isKea: true
}
