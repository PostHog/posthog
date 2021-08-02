import { kea } from 'kea'
import api from 'lib/api'
import { uuid } from 'lib/utils'
import { toast } from 'react-toastify'
import { actionsModel } from '~/models/actionsModel'

export const actionEditLogic = kea({
    key: (props) => props.id || 'new',
    actions: () => ({
        saveAction: true,
        setAction: (action) => ({ action }),
        setCreateNew: (createNew) => ({ createNew }),
        actionAlreadyExists: (actionId) => ({ actionId }),
    }),

    reducers: ({ props }) => ({
        action: [
            props.action,
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

    loaders: ({ props }) => ({
        actionCount: {
            loadActionCount: async () => {
                return (await api.get('api/action/' + props.id + '/count')).count
            },
        },
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
            actionsModel.actions.loadActions() // reload actions so they are immediately available
        },
    }),

    events: ({ actions, props }) => ({
        afterMount: async () => {
            if (props.id) {
                actions.loadActionCount()
            } else {
                actions.setAction({ name: '', steps: [{ isNew: uuid() }] })
            }
        },
    }),
})
