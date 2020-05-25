import { kea } from 'kea'
import api from 'lib/api'
import { uuid } from 'lib/utils'
import { toast } from 'react-toastify'

export const actionEditLogic = kea({
    key: props => props.id || 'new',
    actions: () => ({
        saveAction: true,
        setAction: action => ({ action }),
        setCreateNew: createNew => ({ createNew }),
        setErrorActionId: actionId => ({ actionId }),
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
                setErrorActionId: (_, { actionId }) => actionId,
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
            actions.setErrorActionId(null)
            action.steps = action.steps.map(step => {
                if (step.event == '$pageview') step.selection = ['url', 'url_matching']
                if (step.event != '$pageview' && step.event != '$autocapture') step.selection = ['properties']
                if (!step.selection) return step
                let data = {}
                Object.keys(step).map(key => {
                    data[key] = key == 'id' || key == 'event' || step.selection.indexOf(key) > -1 ? step[key] : null
                })
                return data
            })
            try {
                if (action.id) {
                    action = await api.update(props.apiURL + 'api/action/' + action.id, action)
                } else {
                    action = await api.create(props.apiURL + 'api/action/', action)
                }
            } catch (response) {
                if (response.detail === 'action-exists') {
                    return actions.setErrorActionId(response.id)
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
                const action = await api.get('api/action/' + props.id + '/' + props.params)
                return actions.setAction(action)
            }
            actions.setAction({ name: '', steps: [{ isNew: uuid() }] })
        },
    }),
})
