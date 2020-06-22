import { kea } from 'kea'
import { actionsLogic } from '~/toolbar/elements/actionsLogic'

export const actionsTabLogic = kea({
    actions: {
        selectAction: id => ({ id }),
    },

    reducers: {
        selectedActionId: {
            selectAction: (_, { id }) => id,
        },
    },

    selectors: {
        selectedAction: [
            selectors => [selectors.selectedActionId, actionsLogic.selectors.allActions],
            (selectedActionId, allActions) => allActions.find(a => a.id === selectedActionId),
        ],
    },

    events: () => ({
        afterMount: () => {
            actionsLogic.actions.getActions()
        },
    }),
})
