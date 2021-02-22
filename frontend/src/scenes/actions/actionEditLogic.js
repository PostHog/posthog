import { kea } from 'kea'
import api from 'lib/api'
import { uuid } from 'lib/utils'
import { toast } from 'react-toastify'

export const actionEditLogic = kea({
    key: (props) => props.id || 'new',
    actions: () => ({
        saveAction: true,
        setAction: (action) => ({ action }),
        setCreateNew: (createNew) => ({ createNew }),
        actionAlreadyExists: (actionId) => ({ actionId }),
    }),

    loaders: ({ props }) => ({
        action: {
            loadAction: async () => {
                return await api.get(props.apiURL + 'api/action/' + props.id)
            },
        },
    }),

    reducers: () => ({
        action: [
            null,
            {
                setAction: (_, { action }) => action,
            },
        ],
        errorActionId: [
            null,
            {
                saveAction: () => null,
                actionAlreadyExists: (_, { actionId }) => actionId,
            },
        ],
        createNew: [
            false,
            {
                setCreateNew: (_, { createNew }) => createNew,
            },
        ],
    }),

    listeners: ({ values, props, actions }) => ({
        saveAction: async () => {
            let action = { ...values.action }
            action.steps = action.steps.filter((step) => {
                // Will discard any match groups that were added but for which a type of event selection has not been made
                return step.event
            })
            try {
                let token = props.temporaryToken ? '?temporary_token=' + props.temporaryToken : ''
                if (action.id) {
                    action = await api.update(props.apiURL + 'api/action/' + action.id + '/' + token, action)
                } else {
                    action = await api.create(props.apiURL + 'api/action/' + token, action)
                }
            } catch (response) {
                if (response.detail === 'action-exists') {
                    return actions.actionAlreadyExists(response.id)
                } else {
                    throw response
                }
            }
            toast('Action saved')
            props.onSave(action, values.createNew)
        },
    }),

    events: ({ actions, props }) => ({
        afterMount: async () => {
            if (props.id) {
                const action = await api.get(
                    'api/action/' +
                        props.id +
                        '/?include_count=1' +
                        (props.temporaryToken ? '&temporary_token=' + props.temporaryToken : '')
                )
                actions.setAction(action)
            } else {
                actions.setAction({ name: '', steps: [{ isNew: uuid() }] })
            }
        },
    }),
})
