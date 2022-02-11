import { kea } from 'kea'
import api from 'lib/api'
import { uuid } from 'lib/utils'
import { toast } from 'react-toastify'
import { actionsModel } from '~/models/actionsModel'
import { actionEditLogicType } from './actionEditLogicType'
import { ActionType } from '~/types'

type NewActionType = Partial<ActionType> & Pick<ActionType, 'name' | 'post_to_slack' | 'slack_message_format' | 'steps'>
type ActionEditType = ActionType | NewActionType

export interface ActionEditLogicProps {
    id?: number
    action: ActionEditType
    temporaryToken?: string
    onSave: (action: ActionType) => void
}

export const actionEditLogic = kea<actionEditLogicType<ActionEditLogicProps, ActionEditType>>({
    path: (key) => ['scenes', 'actions', 'actionEditLogic', key],
    props: {} as ActionEditLogicProps,
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
                return props.id ? await api.actions.getCount(props.id) : 0
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
                if (action.id) {
                    action = await api.actions.update(action.id, action, props.temporaryToken)
                } else {
                    action = await api.actions.create(action, props.temporaryToken)
                }
            } catch (response) {
                if (response.code === 'unique') {
                    // Below works because `detail` in the format:
                    // `This project already has an action with this name, ID ${errorActionId}`
                    actions.actionAlreadyExists(response.detail.split(' ').pop())
                    return
                } else {
                    throw response
                }
            }

            toast('Action saved')
            props.onSave(action)
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
