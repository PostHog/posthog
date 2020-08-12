// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic } from 'kea'

export interface compareFilterLogicType extends Logic {
    actionCreators: {
        setCompare: (
            compare: any
        ) => {
            type: 'set compare (lib.components.CompareFilter.compareFilterLogic)'
            payload: {
                compare: any
            }
        }
    }
    actionKeys: {
        'set compare (lib.components.CompareFilter.compareFilterLogic)': 'setCompare'
    }
    actionTypes: {
        setCompare: 'set compare (lib.components.CompareFilter.compareFilterLogic)'
    }
    actions: {
        setCompare: (compare: any) => void
    }
    constants: {}
    defaults: {
        compare: boolean
    }
    events: {}
    key: undefined
    listeners: {}
    path: ['lib', 'components', 'CompareFilter', 'compareFilterLogic']
    pathString: 'lib.components.CompareFilter.compareFilterLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        compare: boolean
    }
    reducerOptions: {}
    reducers: {
        compare: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        compare: boolean
    }
    selectors: {
        compare: (state: any, props: any) => boolean
    }
    sharedListeners: {}
    values: {
        compare: boolean
    }
    _isKea: true
    _isKeaWithKey: false
}
