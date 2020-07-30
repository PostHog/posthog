// Auto-generated with kea-typegen. DO NOT EDIT!

export interface deleteDemoDataLogicType {
    key: any
    actionCreators: {
        deleteDemoData: () => {
            type: 'delete demo data (frontend.src.scenes.setup.DeleteDemoData)'
            payload: {
                value: boolean
            }
        }
        demoDataDeleted: () => {
            type: 'demo data deleted (frontend.src.scenes.setup.DeleteDemoData)'
            payload: {
                value: boolean
            }
        }
    }
    actionKeys: {
        'delete demo data (frontend.src.scenes.setup.DeleteDemoData)': 'deleteDemoData'
        'demo data deleted (frontend.src.scenes.setup.DeleteDemoData)': 'demoDataDeleted'
    }
    actionTypes: {
        deleteDemoData: 'delete demo data (frontend.src.scenes.setup.DeleteDemoData)'
        demoDataDeleted: 'demo data deleted (frontend.src.scenes.setup.DeleteDemoData)'
    }
    actions: {
        deleteDemoData: () => void
        demoDataDeleted: () => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'setup', 'DeleteDemoData']
    pathString: 'frontend.src.scenes.setup.DeleteDemoData'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        isDeleted: boolean
    }
    reducerOptions: any
    reducers: {
        isDeleted: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        isDeleted: boolean
    }
    selectors: {
        isDeleted: (state: any, props: any) => boolean
    }
    values: {
        isDeleted: boolean
    }
    _isKea: true
}
