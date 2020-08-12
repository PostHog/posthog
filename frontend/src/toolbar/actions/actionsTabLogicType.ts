// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic, BreakPointFunction } from 'kea'

export interface actionsTabLogicType<ActionType, ActionForm, FormInstance, AntdFieldData> extends Logic {
    actionCreators: {
        setForm: (
            form: FormInstance
        ) => {
            type: 'set form (toolbar.actions.actionsTabLogic)'
            payload: {
                form: FormInstance
            }
        }
        selectAction: (
            id: number | null
        ) => {
            type: 'select action (toolbar.actions.actionsTabLogic)'
            payload: {
                id: number | null
            }
        }
        newAction: (
            element?: HTMLElement
        ) => {
            type: 'new action (toolbar.actions.actionsTabLogic)'
            payload: {
                element: HTMLElement | null
            }
        }
        inspectForElementWithIndex: (
            index: number | null
        ) => {
            type: 'inspect for element with index (toolbar.actions.actionsTabLogic)'
            payload: {
                index: number | null
            }
        }
        inspectElementSelected: (
            element: HTMLElement,
            index: number | null
        ) => {
            type: 'inspect element selected (toolbar.actions.actionsTabLogic)'
            payload: {
                element: HTMLElement
                index: number | null
            }
        }
        setEditingFields: (
            editingFields: AntdFieldData[]
        ) => {
            type: 'set editing fields (toolbar.actions.actionsTabLogic)'
            payload: {
                editingFields: AntdFieldData[]
            }
        }
        incrementCounter: () => {
            type: 'increment counter (toolbar.actions.actionsTabLogic)'
            payload: {
                value: boolean
            }
        }
        saveAction: (
            formValues: ActionForm
        ) => {
            type: 'save action (toolbar.actions.actionsTabLogic)'
            payload: {
                formValues: ActionForm
            }
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
            showActionsTooltip: boolean
        ) => {
            type: 'set show actions tooltip (toolbar.actions.actionsTabLogic)'
            payload: {
                showActionsTooltip: boolean
            }
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
        setForm: (form: FormInstance) => void
        selectAction: (id: number | null) => void
        newAction: (element?: HTMLElement) => void
        inspectForElementWithIndex: (index: number | null) => void
        inspectElementSelected: (element: HTMLElement, index: number | null) => void
        setEditingFields: (editingFields: AntdFieldData[]) => void
        incrementCounter: () => void
        saveAction: (formValues: ActionForm) => void
        deleteAction: () => void
        showButtonActions: () => void
        hideButtonActions: () => void
        setShowActionsTooltip: (showActionsTooltip: boolean) => void
    }
    constants: {}
    defaults: {
        buttonActionsVisible: boolean
        selectedActionId: number | 'new' | null
        newActionForElement: HTMLElement | null
        inspectingElement: number | null
        editingFields: AntdFieldData[] | null
        form: FormInstance | null
        counter: number
        showActionsTooltip: boolean
    }
    events: {
        afterMount: () => void
    }
    key: undefined
    listeners: {
        selectAction: ((
            payload: {
                id: number | null
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'select action (toolbar.actions.actionsTabLogic)'
                payload: {
                    id: number | null
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        inspectElementSelected: ((
            payload: {
                element: HTMLElement
                index: number | null
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'inspect element selected (toolbar.actions.actionsTabLogic)'
                payload: {
                    element: HTMLElement
                    index: number | null
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        saveAction: ((
            payload: {
                formValues: ActionForm
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'save action (toolbar.actions.actionsTabLogic)'
                payload: {
                    formValues: ActionForm
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        deleteAction: ((
            payload: {
                value: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'delete action (toolbar.actions.actionsTabLogic)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        showButtonActions: ((
            payload: {
                value: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'show button actions (toolbar.actions.actionsTabLogic)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        hideButtonActions: ((
            payload: {
                value: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'hide button actions (toolbar.actions.actionsTabLogic)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        'get actions success (toolbar.actions.actionsLogic)': ((
            payload: {
                allActions: ActionType[]
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'get actions success (toolbar.actions.actionsLogic)'
                payload: {
                    allActions: ActionType[]
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        setShowActionsTooltip: ((
            payload: {
                showActionsTooltip: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'set show actions tooltip (toolbar.actions.actionsTabLogic)'
                payload: {
                    showActionsTooltip: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        'set tab (toolbar.toolbarTabLogic)': ((
            payload: {
                tab: string
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'set tab (toolbar.toolbarTabLogic)'
                payload: {
                    tab: string
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
    }
    path: ['toolbar', 'actions', 'actionsTabLogic']
    pathString: 'toolbar.actions.actionsTabLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        buttonActionsVisible: boolean
        selectedActionId: number | 'new' | null
        newActionForElement: HTMLElement | null
        inspectingElement: number | null
        editingFields: AntdFieldData[] | null
        form: FormInstance | null
        counter: number
        showActionsTooltip: boolean
    }
    reducerOptions: {}
    reducers: {
        buttonActionsVisible: (state: boolean, action: any, fullState: any) => boolean
        selectedActionId: (state: number | 'new' | null, action: any, fullState: any) => number | 'new' | null
        newActionForElement: (state: HTMLElement | null, action: any, fullState: any) => HTMLElement | null
        inspectingElement: (state: number | null, action: any, fullState: any) => number | null
        editingFields: (state: AntdFieldData[] | null, action: any, fullState: any) => AntdFieldData[] | null
        form: (state: FormInstance | null, action: any, fullState: any) => FormInstance | null
        counter: (state: number, action: any, fullState: any) => number
        showActionsTooltip: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        buttonActionsVisible: boolean
        selectedActionId: number | 'new' | null
        newActionForElement: HTMLElement | null
        inspectingElement: number | null
        editingFields: AntdFieldData[] | null
        form: FormInstance | null
        counter: number
        showActionsTooltip: boolean
    }
    selectors: {
        buttonActionsVisible: (state: any, props: any) => boolean
        selectedActionId: (state: any, props: any) => number | 'new' | null
        newActionForElement: (state: any, props: any) => HTMLElement | null
        inspectingElement: (state: any, props: any) => number | null
        editingFields: (state: any, props: any) => AntdFieldData[] | null
        form: (state: any, props: any) => FormInstance | null
        counter: (state: any, props: any) => number
        showActionsTooltip: (state: any, props: any) => boolean
        selectedAction: (state: any, props: any) => ActionType | null
        initialValuesForForm: (state: any, props: any) => ActionForm
        selectedEditedAction: (state: any, props: any) => ActionForm
    }
    sharedListeners: {}
    values: {
        buttonActionsVisible: boolean
        selectedActionId: number | 'new' | null
        newActionForElement: HTMLElement | null
        inspectingElement: number | null
        editingFields: AntdFieldData[] | null
        form: FormInstance | null
        counter: number
        showActionsTooltip: boolean
        selectedAction: ActionType | null
        initialValuesForForm: ActionForm
        selectedEditedAction: ActionForm
    }
    _isKea: true
    _isKeaWithKey: false
    __keaTypeGenInternalSelectorTypes: {
        selectedAction: (arg1: number | 'new' | null, arg2: HTMLElement | null, arg3: ActionType[]) => ActionType | null
        initialValuesForForm: (arg1: ActionType | null) => ActionForm
        selectedEditedAction: (
            arg1: ActionType | null,
            arg2: ActionForm,
            arg3: FormInstance | null,
            arg4: AntdFieldData[] | null,
            arg5: number | null,
            arg6: number
        ) => ActionForm
    }
    __keaTypeGenInternalReducerActions: {
        'get actions success (toolbar.actions.actionsLogic)': (
            allActions: ActionType[]
        ) => {
            type: 'get actions success (toolbar.actions.actionsLogic)'
            payload: {
                allActions: ActionType[]
            }
        }
        'set tab (toolbar.toolbarTabLogic)': (
            tab: ToolbarTab | string
        ) => {
            type: 'set tab (toolbar.toolbarTabLogic)'
            payload: {
                tab: string
            }
        }
    }
}
