// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic } from 'kea'

export interface deleteDemoDataLogicType extends Logic {
    actionCreators: {
        deleteDemoData: () => {
            type: 'delete demo data (scenes.setup.DeleteDemoData)'
            payload: {
                value: boolean
            }
        }
        demoDataDeleted: () => {
            type: 'demo data deleted (scenes.setup.DeleteDemoData)'
            payload: {
                value: boolean
            }
        }
    }
    actionKeys: {
        'delete demo data (scenes.setup.DeleteDemoData)': 'deleteDemoData'
        'demo data deleted (scenes.setup.DeleteDemoData)': 'demoDataDeleted'
    }
    actionTypes: {
        deleteDemoData: 'delete demo data (scenes.setup.DeleteDemoData)'
        demoDataDeleted: 'demo data deleted (scenes.setup.DeleteDemoData)'
    }
    actions: {
        deleteDemoData: () => void
        demoDataDeleted: () => void
    }
    constants: {}
    defaults: {
        isDeleted: boolean
    }
    events: {}
    key: undefined
    listeners: {}
    path: ['scenes', 'setup', 'DeleteDemoData']
    pathString: 'scenes.setup.DeleteDemoData'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        isDeleted: boolean
    }
    reducerOptions: {}
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
    sharedListeners: {}
    values: {
        isDeleted: boolean
    }
    _isKea: true
    _isKeaWithKey: false
}
