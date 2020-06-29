import { kea } from 'kea'
import api from 'lib/api'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { elementToActionStep, actionStepToAntdForm, stepToDatabaseFormat } from '~/toolbar/utils'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { toast } from 'react-toastify'
import { toolbarTabLogic } from '~/toolbar/toolbarTabLogic'
import { dockLogic } from '~/toolbar/dockLogic'

function newAction(element) {
    return {
        name: '',
        steps: [element ? actionStepToAntdForm(elementToActionStep(element), true) : {}],
    }
}

export const actionsTabLogic = kea({
    actions: {
        setForm: form => ({ form }),
        selectAction: id => ({ id }),
        newAction: (element = null) => ({ element }),
        inspectForElementWithIndex: index => ({ index }),
        inspectElementSelected: (element, index) => ({ element, index }),
        setEditingFields: editingFields => ({ editingFields }),
        incrementCounter: true,
        saveAction: formValues => ({ formValues }),
        deleteAction: true,
    },

    reducers: {
        selectedActionId: {
            selectAction: (_, { id }) => id,
            newAction: () => 'new',
        },
        newActionForElement: {
            newAction: (_, { element }) => element,
            selectAction: () => null,
        },
        inspectingElement: {
            inspectForElementWithIndex: (_, { index }) => index,
            inspectElementSelected: () => null,
            selectAction: () => null,
            newAction: () => null,
        },
        editingFields: {
            setEditingFields: (_, { editingFields }) => editingFields,
            selectAction: () => null,
            newAction: () => null,
        },
        form: {
            setForm: (_, { form }) => form,
        },
        counter: [
            0,
            {
                incrementCounter: state => state + 1,
            },
        ],
    },

    selectors: {
        selectedAction: [
            s => [s.selectedActionId, s.newActionForElement, actionsLogic.selectors.allActions],
            (selectedActionId, newActionForElement, allActions) => {
                if (selectedActionId === 'new') {
                    return newAction(newActionForElement)
                }
                return allActions.find(a => a.id === selectedActionId)
            },
        ],
        initialValuesForForm: [
            s => [s.selectedAction],
            selectedAction =>
                selectedAction ? { ...selectedAction, steps: selectedAction.steps.map(actionStepToAntdForm) } : {},
        ],
        selectedEditedAction: [
            // `editingFields` don't update on values.form.setFields(fields), so reloading by tagging a few other selectors
            s => [s.selectedAction, s.initialValuesForForm, s.form, s.editingFields, s.inspectingElement, s.counter],
            (selectedAction, initialValuesForForm, form) => {
                return selectedAction ? { ...initialValuesForForm, ...(form?.getFieldValue() || {}) } : null
            },
        ],
    },

    listeners: ({ actions, values }) => ({
        selectAction: ({ id }) => {
            if (id) {
                if (dockLogic.values.mode === 'button') {
                    dockLogic.actions.dock()
                }
                toolbarTabLogic.actions.setTab('actions')
            }
        },
        inspectElementSelected: ({ element, index }) => {
            if (values.form) {
                const actionStep = actionStepToAntdForm(elementToActionStep(element), true)
                const fields = Object.entries(actionStep).map(([key, value]) => {
                    return { name: ['steps', index, key], value }
                })
                values.form.setFields(fields)
                actions.incrementCounter()
            }
        },
        saveAction: async ({ formValues }, breakpoint) => {
            const actionToSave = {
                ...formValues,
                steps: formValues.steps.map(stepToDatabaseFormat),
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
        [toolbarTabLogic.actions.setTab]: ({ tab }) => {
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
