import { kea } from 'kea'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { elementToActionStep, actionStepToAntdForm } from '~/toolbar/elements/utils'

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
                return selectedAction ? form?.getFieldValue() || initialValuesForForm : null
            },
        ],
    },

    listeners: ({ actions, values }) => ({
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
    }),

    events: {
        afterMount: () => {
            actionsLogic.actions.getActions()
        },
    },
})
