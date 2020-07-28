// Auto-generated with kea-typegen. DO NOT EDIT!

export interface actionsTabLogicType {
    key: any
    actionCreators: {
        setForm: (
            form: any
        ) => {
            type: 'set form (toolbar.actions.actionsTabLogic)'
            payload: { form: any }
        }
        selectAction: (
            id: any
        ) => {
            type: 'select action (toolbar.actions.actionsTabLogic)'
            payload: { id: any }
        }
        newAction: (
            element?: any
        ) => {
            type: 'new action (toolbar.actions.actionsTabLogic)'
            payload: { element: any }
        }
        inspectForElementWithIndex: (
            index: any
        ) => {
            type: 'inspect for element with index (toolbar.actions.actionsTabLogic)'
            payload: { index: any }
        }
        inspectElementSelected: (
            element: any,
            index: any
        ) => {
            type: 'inspect element selected (toolbar.actions.actionsTabLogic)'
            payload: { element: any; index: any }
        }
        setEditingFields: (
            editingFields: any
        ) => {
            type: 'set editing fields (toolbar.actions.actionsTabLogic)'
            payload: { editingFields: any }
        }
        incrementCounter: () => {
            type: 'increment counter (toolbar.actions.actionsTabLogic)'
            payload: {
                value: boolean
            }
        }
        saveAction: (
            formValues: any
        ) => {
            type: 'save action (toolbar.actions.actionsTabLogic)'
            payload: { formValues: any }
        }
        deleteAction: () => {
            type: 'delete action (toolbar.actions.actionsTabLogic)'
            payload: {
                value: boolean
            }
        }
        showButtonActions: () => {
            type: 'show button actions (toolbar.actions.actionsTabLogic)'
            payload: {
                value: boolean
            }
        }
        hideButtonActions: () => {
            type: 'hide button actions (toolbar.actions.actionsTabLogic)'
            payload: {
                value: boolean
            }
        }
        setShowActionsTooltip: (
            showActionsTooltip: any
        ) => {
            type: 'set show actions tooltip (toolbar.actions.actionsTabLogic)'
            payload: { showActionsTooltip: any }
        }
    }
    actionKeys: {
        'set form (toolbar.actions.actionsTabLogic)': 'setForm'
        'select action (toolbar.actions.actionsTabLogic)': 'selectAction'
        'new action (toolbar.actions.actionsTabLogic)': 'newAction'
        'inspect for element with index (toolbar.actions.actionsTabLogic)': 'inspectForElementWithIndex'
        'inspect element selected (toolbar.actions.actionsTabLogic)': 'inspectElementSelected'
        'set editing fields (toolbar.actions.actionsTabLogic)': 'setEditingFields'
        'increment counter (toolbar.actions.actionsTabLogic)': 'incrementCounter'
        'save action (toolbar.actions.actionsTabLogic)': 'saveAction'
        'delete action (toolbar.actions.actionsTabLogic)': 'deleteAction'
        'show button actions (toolbar.actions.actionsTabLogic)': 'showButtonActions'
        'hide button actions (toolbar.actions.actionsTabLogic)': 'hideButtonActions'
        'set show actions tooltip (toolbar.actions.actionsTabLogic)': 'setShowActionsTooltip'
    }
    actionTypes: {
        setForm: 'set form (toolbar.actions.actionsTabLogic)'
        selectAction: 'select action (toolbar.actions.actionsTabLogic)'
        newAction: 'new action (toolbar.actions.actionsTabLogic)'
        inspectForElementWithIndex: 'inspect for element with index (toolbar.actions.actionsTabLogic)'
        inspectElementSelected: 'inspect element selected (toolbar.actions.actionsTabLogic)'
        setEditingFields: 'set editing fields (toolbar.actions.actionsTabLogic)'
        incrementCounter: 'increment counter (toolbar.actions.actionsTabLogic)'
        saveAction: 'save action (toolbar.actions.actionsTabLogic)'
        deleteAction: 'delete action (toolbar.actions.actionsTabLogic)'
        showButtonActions: 'show button actions (toolbar.actions.actionsTabLogic)'
        hideButtonActions: 'hide button actions (toolbar.actions.actionsTabLogic)'
        setShowActionsTooltip: 'set show actions tooltip (toolbar.actions.actionsTabLogic)'
    }
    actions: {
        setForm: (
            form: any
        ) => {
            type: 'set form (toolbar.actions.actionsTabLogic)'
            payload: { form: any }
        }
        selectAction: (
            id: any
        ) => {
            type: 'select action (toolbar.actions.actionsTabLogic)'
            payload: { id: any }
        }
        newAction: (
            element?: any
        ) => {
            type: 'new action (toolbar.actions.actionsTabLogic)'
            payload: { element: any }
        }
        inspectForElementWithIndex: (
            index: any
        ) => {
            type: 'inspect for element with index (toolbar.actions.actionsTabLogic)'
            payload: { index: any }
        }
        inspectElementSelected: (
            element: any,
            index: any
        ) => {
            type: 'inspect element selected (toolbar.actions.actionsTabLogic)'
            payload: { element: any; index: any }
        }
        setEditingFields: (
            editingFields: any
        ) => {
            type: 'set editing fields (toolbar.actions.actionsTabLogic)'
            payload: { editingFields: any }
        }
        incrementCounter: () => {
            type: 'increment counter (toolbar.actions.actionsTabLogic)'
            payload: {
                value: boolean
            }
        }
        saveAction: (
            formValues: any
        ) => {
            type: 'save action (toolbar.actions.actionsTabLogic)'
            payload: { formValues: any }
        }
        deleteAction: () => {
            type: 'delete action (toolbar.actions.actionsTabLogic)'
            payload: {
                value: boolean
            }
        }
        showButtonActions: () => {
            type: 'show button actions (toolbar.actions.actionsTabLogic)'
            payload: {
                value: boolean
            }
        }
        hideButtonActions: () => {
            type: 'hide button actions (toolbar.actions.actionsTabLogic)'
            payload: {
                value: boolean
            }
        }
        setShowActionsTooltip: (
            showActionsTooltip: any
        ) => {
            type: 'set show actions tooltip (toolbar.actions.actionsTabLogic)'
            payload: { showActionsTooltip: any }
        }
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['toolbar', 'actions', 'actionsTabLogic']
    pathString: 'toolbar.actions.actionsTabLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        buttonActionsVisible: boolean
        selectedActionId: any
        newActionForElement: any
        inspectingElement: any
        editingFields: any
        form: any
        counter: number
        showActionsTooltip: boolean
    }
    reducerOptions: any
    reducers: {
        buttonActionsVisible: (state: boolean, action: any, fullState: any) => boolean
        selectedActionId: (state: any, action: any, fullState: any) => any
        newActionForElement: (state: any, action: any, fullState: any) => any
        inspectingElement: (state: any, action: any, fullState: any) => any
        editingFields: (state: any, action: any, fullState: any) => any
        form: (state: any, action: any, fullState: any) => any
        counter: (state: number, action: any, fullState: any) => number
        showActionsTooltip: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        buttonActionsVisible: boolean
        selectedActionId: any
        newActionForElement: any
        inspectingElement: any
        editingFields: any
        form: any
        counter: number
        showActionsTooltip: boolean
    }
    selectors: {
        buttonActionsVisible: (state: any, props: any) => boolean
        selectedActionId: (state: any, props: any) => any
        newActionForElement: (state: any, props: any) => any
        inspectingElement: (state: any, props: any) => any
        editingFields: (state: any, props: any) => any
        form: (state: any, props: any) => any
        counter: (state: any, props: any) => number
        showActionsTooltip: (state: any, props: any) => boolean
        selectedAction: (state: any, props: any) => any
        initialValuesForForm: (state: any, props: any) => any
        selectedEditedAction: (state: any, props: any) => any
    }
    values: {
        buttonActionsVisible: boolean
        selectedActionId: any
        newActionForElement: any
        inspectingElement: any
        editingFields: any
        form: any
        counter: number
        showActionsTooltip: boolean
        selectedAction: any
        initialValuesForForm: any
        selectedEditedAction: any
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        selectedAction: (arg1: any, arg2: any, arg3: any) => any
        initialValuesForForm: (arg1: any) => any
        selectedEditedAction: (arg1: any, arg2: any, arg3: any, arg4: any, arg5: any, arg6: any) => any
    }
}
