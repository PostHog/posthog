import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import api from 'lib/api'
import { deleteWithUndo, uuid } from 'lib/utils'
import { actionsModel } from '~/models/actionsModel'
import type { actionEditLogicType } from './actionEditLogicType'
import { ActionStepType, ActionType } from '~/types'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'
import { beforeUnload, router, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { Link } from 'lib/lemon-ui/Link'
import { tagsModel } from '~/models/tagsModel'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

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
    connect({ actions: [tagsModel, ['loadTags']], values: [sceneLogic, ['activeScene']] }),
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
        wasDeleted: [
            false,
            {
                deleteAction: () => true,
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
                    actions.loadActionCount()
                    actions.loadTags() // reload tags in case new tags are being saved
                    return action
                },
            },
        ],
    })),

    listeners(({ values, actions }) => ({
        deleteAction: async () => {
            await deleteWithUndo({
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

    urlToAction(({ actions }) => ({
        [urls.createAction()]: (_, searchParams) => {
            try {
                if (searchParams.copy) {
                    const {
                        id: _id,
                        created_at: _created_at,
                        created_by: _created_by,
                        last_calculated_at: _last_calculated_at,
                        ...actionToCopy
                    } = searchParams.copy

                    actions.setAction(
                        {
                            ...actionToCopy,
                            steps: actionToCopy.steps.map((s: ActionStepType) => {
                                const { id: _id, ...step } = s
                                return { ...step, isNew: uuid() }
                            }),
                            name: `${actionToCopy.name} (copy)`,
                        },
                        { merge: false }
                    )
                }
            } catch (e) {
                throw new Error('Could not parse action to copy from URL')
            }
        },
    })),

    beforeUnload(({ values }) => ({
        enabled: () => values.activeScene !== Scene.Action && values.actionChanged && !values.wasDeleted,
        message: `Leave action?\nChanges you made will be discarded.`,
    })),
])
