import { kea } from 'kea'
import { actionsLogic } from '~/toolbar/elements/actionsLogic'

export const actionsTabLogic = kea({
    events: () => ({
        afterMount: () => {
            actionsLogic.actions.getActions()
        },
    }),
})
