import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { uuid } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { actionsModel } from '~/models/actionsModel'
import { tagsModel } from '~/models/tagsModel'
import { ActionStepType, ActionType } from '~/types'

import type { actionEditLogicType } from './actionEditLogicType'
import { actionLogic } from './actionLogic'

export interface SetActionProps {
    merge?: boolean
}

export interface ActionEditLogicProps {
    id?: number
    action?: ActionType | null
}

export const actionEditLogic = kea<actionEditLogicType>([
    path((key) => ['scenes', 'actions', 'actionEditLogic', key]),
    props({} as ActionEditLogicProps),
    key((props) => props.id || 'new'),
    connect({
        actions: [
            actionsModel,
            ['loadActions'],
            eventDefinitionsTableLogic,
            ['loadEventDefinitions'],
            tagsModel,
            ['loadTags'],
        ],
        values: [sceneLogic, ['activeScene']],
    }),
    actions({
        setAction: (action: Partial<ActionType>, options: SetActionProps = { merge: true }) => ({
            action,
            options,
        }),
        setCreateNew: (createNew: boolean) => ({ createNew }),
        actionAlreadyExists: (actionId: number | null) => ({ actionId }),
        deleteAction: true,
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
            defaults: { ...props.action } as ActionType,
            submit: (action) => {
                actions.saveAction(action)
            },
        },
    })),

    loaders(({ props, values, actions }) => ({
        action: [
            { ...props.action } as ActionType,
            {
                setAction: ({ action, options: { merge } }) =>
                    (merge ? { ...values.action, ...action } : action) as ActionType,
                saveAction: async (updatedAction: ActionType, breakpoint) => {
                    let action: ActionType

                    try {
                        if (updatedAction.id) {
                            action = await api.actions.update(updatedAction.id, updatedAction)
                        } else {
                            action = await api.actions.create(updatedAction)
                        }
                        breakpoint()
                    } catch (response: any) {
                        if (response.code === 'unique') {
                            // Below works because `detail` in the format:
                            // `This project already has an action with this name, ID ${errorActionId}`
                            const dupeId = response.detail.split(' ').pop()

                            lemonToast.error(
                                <>
                                    Action with this name already exists. <Link to={urls.action(dupeId)}>Edit it</Link>
                                </>
                            )

                            return { ...updatedAction }
                        }
                        throw response
                    }

                    lemonToast.success(`Action saved`)
                    if (!props.id) {
                        router.actions.push(urls.action(action.id))
                    } else {
                        const id = parseInt(props.id.toString()) // props.id can be a string
                        const logic = actionLogic.findMounted(id)
                        logic?.actions.loadActionSuccess(action)
                    }

                    // reload actions so they are immediately available throughout the app
                    actions.loadEventDefinitions()
                    actions.loadActions()
                    actions.loadTags() // reload tags in case new tags are being saved
                    return action
                },
            },
        ],
    })),

    listeners(({ values, actions }) => ({
        deleteAction: async () => {
            try {
                await deleteWithUndo({
                    endpoint: api.actions.determineDeleteEndpoint(),
                    object: values.action,
                    callback: () => {
                        router.actions.push(urls.actions())
                        actions.loadActions()
                    },
                })
            } catch (e: any) {
                lemonToast.error(`Error deleting action: ${e.detail}`)
            }
        },
    })),

    afterMount(({ actions, props }) => {
        if (!props.id) {
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
