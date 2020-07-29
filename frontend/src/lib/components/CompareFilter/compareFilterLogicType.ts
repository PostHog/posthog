// Auto-generated with kea-typegen. DO NOT EDIT!

export interface compareFilterLogicType {
    key: any
    actionCreators: {
        setCompare: (
            compare: any
        ) => {
            type: 'set compare (lib.components.CompareFilter.compareFilterLogic)'
            payload: { compare: any }
        }
    }
    actionKeys: {
        'set compare (lib.components.CompareFilter.compareFilterLogic)': 'setCompare'
    }
    actionTypes: {
        setCompare: 'set compare (lib.components.CompareFilter.compareFilterLogic)'
    }
    actions: {
        setCompare: (
            compare: any
        ) => {
            type: 'set compare (lib.components.CompareFilter.compareFilterLogic)'
            payload: { compare: any }
        }
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['lib', 'components', 'CompareFilter', 'compareFilterLogic']
    pathString: 'lib.components.CompareFilter.compareFilterLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        compare: boolean
    }
    reducerOptions: any
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
    values: {
        compare: boolean
    }
    _isKea: true
}
