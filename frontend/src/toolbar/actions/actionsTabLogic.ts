import { kea } from 'kea'
import api from 'lib/api'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { elementToActionStep, actionStepToAntdForm, stepToDatabaseFormat } from '~/toolbar/utils'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { toast } from 'react-toastify'
import { toolbarTabLogic } from '~/toolbar/toolbarTabLogic'
import { dockLogic } from '~/toolbar/dockLogic'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { actionsTabLogicType } from '~/toolbar/actions/actionsTabLogicType'
import { ActionType, ToolbarTab } from '~/types'
import { ActionForm, ActionStepForm } from '~/toolbar/types'
import { FormInstance } from 'antd/es/form'

function newAction(element: HTMLElement | null): Partial<ActionType> {
    return {
        name: '',
        steps: [element ? actionStepToAntdForm(elementToActionStep(element), true) : {}],
    }
}

export const actionsTabLogic = kea<actionsTabLogicType<ActionType, ActionForm, ActionStepForm, FormInstance>>({
    actions: {
        setForm: (form: FormInstance) => ({ form }),
        selectAction: (id: number | null) => ({ id }),
        newAction: (element?: HTMLElement) => ({ element }),
        inspectForElementWithIndex: (index: number) => ({ index }),
        inspectElementSelected: (element: HTMLElement, index: number | null) => ({ element, index }),
        setEditingFields: (editingFields: ActionStepForm) => ({ editingFields }),
        incrementCounter: true,
        saveAction: (formValues: ActionForm) => ({ formValues }),
        deleteAction: true,
        showButtonActions: true,
        hideButtonActions: true,
        setShowActionsTooltip: (showActionsTooltip: boolean) => ({ showActionsTooltip }),
    },

    reducers: {
        buttonActionsVisible: [
            false,
            {
                showButtonActions: () => true,
                hideButtonActions: () => false,
            },
        ],
        selectedActionId: [
            null as number | 'new' | null,
            {
                selectAction: (_, { id }) => id,
                newAction: () => 'new',
            },
        ],
        newActionForElement: [
            null as HTMLElement | null,
            {
                newAction: (_, { element }) => element,
                selectAction: () => null,
            },
        ],
        inspectingElement: [
            null as number | null,
            {
                inspectForElementWithIndex: (_, { index }) => index,
                inspectElementSelected: () => null,
                selectAction: () => null,
                newAction: () => null,
            },
        ],
        editingFields: [
            null as ActionStepForm | null,
            {
                setEditingFields: (_, { editingFields }) => editingFields,
                selectAction: () => null,
                newAction: () => null,
            },
        ],
        form: [
            null as FormInstance | null,
            {
                setForm: (_, { form }) => form,
            },
        ],
        counter: [
            0,
            {
                incrementCounter: (state) => state + 1,
            },
        ],
        showActionsTooltip: [
            false,
            {
                setShowActionsTooltip: (_, { showActionsTooltip }) => showActionsTooltip,
            },
        ],
    },

    selectors: {
        selectedAction: [
            (s) => [s.selectedActionId, s.newActionForElement, actionsLogic.selectors.allActions],
            (selectedActionId, newActionForElement, allActions): ActionType | null => {
                if (selectedActionId === 'new') {
                    return newAction(newActionForElement)
                }
                return allActions.find((a) => a.id === selectedActionId) || null
            },
        ],
        initialValuesForForm: [
            (s) => [s.selectedAction],
            (selectedAction): ActionForm =>
                selectedAction
                    ? {
                          ...selectedAction,
                          steps: selectedAction.steps?.map((step) => actionStepToAntdForm(step)) || [],
                      }
                    : { steps: [] },
        ],
        selectedEditedAction: [
            // `editingFields` don't update on values.form.setFields(fields), so reloading by tagging a few other selectors
            (s) => [s.selectedAction, s.initialValuesForForm, s.form, s.editingFields, s.inspectingElement, s.counter],
            (selectedAction, initialValuesForForm, form): ActionForm => {
                return selectedAction ? { ...initialValuesForForm, ...(form?.getFieldValue('') || {}) } : null
            },
        ],
    },

    listeners: ({ actions, values }) => ({
        selectAction: ({ id }) => {
            if (id) {
                if (dockLogic.values.mode === 'button') {
                    if (!values.buttonActionsVisible) {
                        actions.showButtonActions()
                    }
                    if (!toolbarButtonLogic.values.actionsInfoVisible) {
                        toolbarButtonLogic.actions.showActionsInfo()
                    }
                } else {
                    if (toolbarTabLogic.values.tab !== 'actions') {
                        toolbarTabLogic.actions.setTab('actions')
                    }
                }
            }
        },
        inspectElementSelected: ({ element, index }) => {
            if (values.form) {
                const actionStep = actionStepToAntdForm(elementToActionStep(element), true)
                const fields = Object.entries(actionStep).map(([key, value]) => {
                    return { name: ['steps', index || 0, key], value }
                })
                values.form.setFields(fields)
                actions.incrementCounter()
            }
        },
        saveAction: async ({ formValues }, breakpoint) => {
            const actionToSave = {
                ...formValues,
                steps: formValues.steps?.map(stepToDatabaseFormat) || [],
            }
            const { apiURL, temporaryToken } = toolbarLogic.values
            const { selectedActionId } = values

            let response
            if (selectedActionId && selectedActionId !== 'new') {
                response = await api.update(
                    `${apiURL}${
                        apiURL.endsWith('/') ? '' : '/'
                    }api/action/${selectedActionId}/?temporary_token=${temporaryToken}`,
                    actionToSave
                )
            } else {
                response = await api.create(
                    `${apiURL}${apiURL.endsWith('/') ? '' : '/'}api/action/?temporary_token=${temporaryToken}`,
                    actionToSave
                )
            }
            breakpoint()

            actionsLogic.actions.updateAction({ action: response })
            actions.selectAction(null)
            toast('Action saved!')
        },
        deleteAction: async () => {
            const { apiURL, temporaryToken } = toolbarLogic.values
            const { selectedActionId } = values
            if (selectedActionId && selectedActionId !== 'new') {
                await api.delete(
                    `${apiURL}${
                        apiURL.endsWith('/') ? '' : '/'
                    }api/action/${selectedActionId}/?temporary_token=${temporaryToken}`
                )

                actionsLogic.actions.deleteAction({ id: selectedActionId })
                actions.selectAction(null)
                toast('Action deleted!')
            }
        },
        showButtonActions: () => {
            actionsLogic.actions.getActions()
        },
        hideButtonActions: () => {
            actions.setShowActionsTooltip(false)
        },
        [actionsLogic.actionTypes.getActionsSuccess]: () => {
            actions.setShowActionsTooltip(true)
        },
        setShowActionsTooltip: async ({ showActionsTooltip }, breakpoint) => {
            if (showActionsTooltip) {
                await breakpoint(1000)
                actions.setShowActionsTooltip(false)
            }
        },
        // not sure why { tab: ToolbarTab } needs to be manually added...
        [toolbarTabLogic.actionTypes.setTab]: ({ tab }: { tab: ToolbarTab }) => {
            if (tab === 'actions') {
                actionsLogic.actions.getActions()
            }
        },
    }),

    events: {
        afterMount: () => {
            const { mode } = dockLogic.values
            const { tab } = toolbarTabLogic.values
            if (tab === 'actions' && mode === 'dock') {
                actionsLogic.actions.getActions()
            }
        },
    },
})
