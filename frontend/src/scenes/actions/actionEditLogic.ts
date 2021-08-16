import { kea } from 'kea'
import api from 'lib/api'
import { uuid } from 'lib/utils'
import { toast } from 'react-toastify'
import { actionsModel } from '~/models/actionsModel'
import { actionEditLogicType } from './actionEditLogicType'
import { ActionStepType, ActionType } from '~/types'

interface NewActionType {
    name: string
    steps: ActionStepType[]
}

type ActionEditType = ActionType | NewActionType

interface Props {
    id: string
    apiURL: string
    action: ActionEditType
    temporaryToken: string
    onSave: (action: ActionType, createNew: boolean) => void
}

export const actionEditLogic = kea<actionEditLogicType<ActionEditType, Props>>({
    props: {} as Props,
    key: (props) => props.id || 'new',
    actions: () => ({
        saveAction: true,
        setAction: (action: ActionEditType) => ({ action }),
        setCreateNew: (createNew: boolean) => ({ createNew }),
        actionAlreadyExists: (actionId: number | null) => ({ actionId }),
    }),

    reducers: ({ props }) => ({
        action: [
            props.action as ActionEditType,
            {
                setAction: (_, { action }) => action,
            },
        ],
        errorActionId: [
            null as number | null,
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
            let action = Object.assign({}, values.action) as ActionType

            action.steps = action.steps
                ? action.steps.filter((step) => {
                      // Will discard any match groups that were added but for which a type of event selection has not been made
                      return step.event
                  })
                : []
            try {
                const token = props.temporaryToken ? '?temporary_token=' + props.temporaryToken : ''
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
