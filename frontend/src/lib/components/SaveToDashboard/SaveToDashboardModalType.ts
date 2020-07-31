// Auto-generated with kea-typegen. DO NOT EDIT!

export interface saveToDashboardModalLogicType {
    key: undefined
    actionCreators: {
        addNewDashboard: () => {
            type: 'add new dashboard (lib.components.SaveToDashboard.SaveToDashboardModal)'
            payload: {
                value: boolean
            }
        }
    }
    actionKeys: {
        'add new dashboard (lib.components.SaveToDashboard.SaveToDashboardModal)': 'addNewDashboard'
    }
    actionTypes: {
        addNewDashboard: 'add new dashboard (lib.components.SaveToDashboard.SaveToDashboardModal)'
    }
    actions: {
        addNewDashboard: () => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: {}
    events: any
    path: ['lib', 'components', 'SaveToDashboard', 'SaveToDashboardModal']
    pathString: 'lib.components.SaveToDashboard.SaveToDashboardModal'
    props: Record<string, unknown>
    reducer: (state: any, action: () => any, fullState: any) => {}
    reducerOptions: any
    reducers: {}
    selector: (state: any) => {}
    selectors: {}
    values: {}
    _isKea: true
}
