import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import api from 'lib/api'
import { deleteWithUndo, uuid } from 'lib/utils'
import { actionsModel } from '~/models/actionsModel'
import type { actionEditLogicType } from './actionEditLogicType'
import { ActionType } from '~/types'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { Link } from 'lib/lemon-ui/Link'
import { tagsModel } from '~/models/tagsModel'

export type NewActionType = Partial<ActionType> &
    Pick<ActionType, 'name' | 'post_to_slack' | 'slack_message_format' | 'steps'>
export type ActionEditType = ActionType | NewActionType

export interface SetActionProps {
    merge?: boolean
}

export interface ActionEditLogicProps {
    id?: number
    action: ActionEditType
    temporaryToken?: string
    onSave: (action: ActionType) => void
}

export const actionEditLogic = kea<actionEditLogicType>([
    path(['scenes', 'actions', 'actionEditLogic']),
    props({} as ActionEditLogicProps),
    key((props) => props.id || 'new'),
    connect({ actions: [tagsModel, ['loadTags']] }),
    actions({
        setAction: (action: Partial<ActionEditType>, options: SetActionProps = { merge: true }) => ({
            action,
            options,
        }),
        setCreateNew: (createNew: boolean) => ({ createNew }),
        actionAlreadyExists: (actionId: number | null) => ({ actionId }),
        deleteAction: true,
    }),

    connect({
        actions: [actionsModel, ['loadActions'], eventDefinitionsTableLogic, ['loadEventDefinitions']],
    }),

    reducers({
        createNew: [
            false,
            {
                setCreateNew: (_, { createNew }) => createNew,
            },
        ],
    }),

    forms(({ actions, props }) => ({
        action: {
            defaults: { ...props.action } as ActionEditType,
            errors: ({ name }) => ({
                name: !name ? 'You need to set a name' : null,
            }),
            submit: (action) => {
                actions.saveAction(action)
            },
        },
    })),

    loaders(({ props, values, actions }) => ({
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
                saveAction: async (updatedAction: ActionEditType, breakpoint) => {
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
                        breakpoint()
                    } catch (response: any) {
                        if (response.code === 'unique') {
                            // Below works because `detail` in the format:
                            // `This project already has an action with this name, ID ${errorActionId}`
                            const dupeId = response.detail.split(' ').pop()

                            lemonToast.error(
                                <>
                                    Action with this name already exists.{' '}
                                    <Link to={urls.action(dupeId)}>Click here to edit.</Link>
                                </>
                            )

                            return action
                        }
                        throw response
                    }

                    lemonToast.success(`Action saved`)
                    props.onSave(action as ActionType)
                    // reload actions so they are immediately available throughout the app
                    actions.loadEventDefinitions(null)
                    actions.loadActions()
                    actions.loadTags() // reload tags in case new tags are being saved
                    return action
                },
            },
        ],
    })),

    listeners(({ values, actions }) => ({
        deleteAction: () => {
            deleteWithUndo({
                endpoint: api.actions.determineDeleteEndpoint(),
                object: values.action,
                callback: () => {
                    router.actions.push(urls.actions())
                    actions.loadActions()
                },
            })
        },
    })),

    afterMount(({ actions, props }) => {
        if (props.id) {
            actions.loadActionCount()
        } else {
            actions.setAction({ name: '', steps: [{ isNew: uuid() }] }, { merge: false })
        }
    }),
])
