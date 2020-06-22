import { kea } from 'kea'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'

function newAction() {
    return {
        name: '',
        steps: [{ empty: true }],
    }
}

export const actionsTabLogic = kea({
    actions: {
        selectAction: id => ({ id }),
        newAction: true,

        inspectForElementWithIndex: index => ({ index }),
    },

    reducers: {
        selectedActionId: {
            selectAction: (_, { id }) => id,
            newAction: () => 'new',
        },
        inspectingElement: {
            inspectForElementWithIndex: (_, { index }) => index,
            selectAction: () => null,
            newAction: () => null,
        },
    },

    selectors: {
        selectedAction: [
            selectors => [selectors.selectedActionId, actionsLogic.selectors.allActions],
            (selectedActionId, allActions) => {
                if (selectedActionId === 'new') {
                    return newAction()
                }
                return allActions.find(a => a.id === selectedActionId)
            },
        ],
    },

    events: () => ({
        afterMount: () => {
            actionsLogic.actions.getActions()
        },
    }),
})
