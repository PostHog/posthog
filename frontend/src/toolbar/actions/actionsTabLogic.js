import { kea } from 'kea'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { elementToActionStep, actionStepToAntdForm } from '~/toolbar/elements/utils'

function newAction() {
    return {
        name: '',
        steps: [{ empty: true }],
    }
}

export const actionsTabLogic = kea({
    actions: {
        setForm: form => ({ form }),
        selectAction: id => ({ id }),
        newAction: true,
        inspectForElementWithIndex: index => ({ index }),
        inspectElementSelected: (element, index) => ({ element, index }),
        setEditingFields: editingFields => ({ editingFields }),
    },

    reducers: {
        selectedActionId: {
            selectAction: (_, { id }) => id,
            newAction: () => 'new',
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
    },

    selectors: {
        selectedAction: [
            s => [s.selectedActionId, actionsLogic.selectors.allActions],
            (selectedActionId, allActions) => {
                if (selectedActionId === 'new') {
                    return newAction()
                }
                return allActions.find(a => a.id === selectedActionId)
            },
        ],
        initialValuesForForm: [
            s => [s.selectedAction],
            selectedAction => ({ ...selectedAction, steps: selectedAction.steps.map(actionStepToAntdForm) }),
        ],
    },

    listeners: ({ values }) => ({
        inspectElementSelected: ({ element, index }) => {
            if (values.form) {
                const actionStep = actionStepToAntdForm(elementToActionStep(element), true)
                values.form.setFields([{ name: ['steps', index], value: actionStep }])
            }
        },
    }),

    events: {
        afterMount: () => {
            actionsLogic.actions.getActions()
        },
    },
})
