import { kea } from 'kea'
import api from 'lib/api'
import { uuid } from 'lib/utils'
import { actionsModel } from '~/models/actionsModel'
import { actionEditLogicType } from './actionEditLogicType'
import { ActionType } from '~/types'
import { lemonToast } from 'lib/components/lemonToast'

type NewActionType = Partial<ActionType> & Pick<ActionType, 'name' | 'post_to_slack' | 'slack_message_format' | 'steps'>
type ActionEditType = ActionType | NewActionType

interface SetActionProps {
    merge?: boolean
}

export interface ActionEditLogicProps {
    id?: number
    action: ActionEditType
    temporaryToken?: string
    onSave: (action: ActionType) => void
}

export const actionEditLogic = kea<actionEditLogicType<ActionEditLogicProps, ActionEditType, SetActionProps>>({
    path: (key) => ['scenes', 'actions', 'actionEditLogic', key],
    props: {} as ActionEditLogicProps,
    key: (props) => props.id || 'new',
    actions: () => ({
        setAction: (action: Partial<ActionEditType>, options: SetActionProps = { merge: true }) => ({
            action,
            options,
        }),
        setCreateNew: (createNew: boolean) => ({ createNew }),
        actionAlreadyExists: (actionId: number | null) => ({ actionId }),
    }),

    reducers: () => ({
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

    forms: ({ actions, props }) => ({
        action: {
            defaults: { ...props.action } as ActionEditType,
            validator: ({ name }) => ({
                name: !name ? 'You need to set a name' : null,
            }),
            submit: (action) => {
                actions.saveAction(action)
            },
        },
    }),

    loaders: ({ props, values, actions }) => ({
        actionCount: {
            loadActionCount: async () => {
                return props.id ? await api.actions.getCount(props.id) : 0
            },
        },
        action: [
            { ...props.action } as ActionEditType,
            {
                setAction: ({ action, options: { merge } }) =>
                    (merge ? { ...values.action, ...action } : action) as ActionEditType,
                saveAction: async (updatedAction: ActionEditType) => {
                    let action = { ...updatedAction }

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
                    } catch (response: any) {
                        if (response.code === 'unique') {
                            // Below works because `detail` in the format:
                            // `This project already has an action with this name, ID ${errorActionId}`
                            actions.actionAlreadyExists(response.detail.split(' ').pop())
                            return action
                        } else {
                            throw response
                        }
                    }
                    return action
                },
            },
        ],
    }),

    listeners: ({ props }) => ({
        saveActionSuccess: ({ action }) => {
            lemonToast.success('Action saved')
            props.onSave(action as ActionType)
            actionsModel.actions.loadActions() // reload actions so they are immediately available
        },
    }),

    events: ({ actions, props }) => ({
        afterMount: async () => {
            if (props.id) {
                actions.loadActionCount()
            } else {
                actions.setAction({ name: '', steps: [{ isNew: uuid() }] }, { merge: false })
            }
        },
    }),
})
