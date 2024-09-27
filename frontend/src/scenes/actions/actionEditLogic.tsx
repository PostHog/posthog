import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { hogFunctionListLogic } from 'scenes/pipeline/hogfunctions/list/hogFunctionListLogic'
import { sceneLogic } from 'scenes/sceneLogic'
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

export const DEFAULT_ACTION_STEP: ActionStepType = {
    event: '$pageview',
    href_matching: 'contains',
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
        migrateToHogFunction: true,
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
            defaults:
                props.action ??
                ({
                    name: '',
                    steps: [DEFAULT_ACTION_STEP],
                } as ActionType),

            submit: async (updatedAction, breakpoint) => {
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
                                Action with this name already exists.{' '}
                                <Link to={urls.action(dupeId)} target="_blank">
                                    Edit it here
                                </Link>
                            </>
                        )

                        return { ...updatedAction }
                    }
                    throw response
                }

                lemonToast.success(`Action saved`)
                actions.resetAction(updatedAction)
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
    })),

    selectors({
        hasCohortFilters: [
            (s) => [s.action],
            (action) => action?.steps?.some((step) => step.properties?.find((p) => p.type === 'cohort')) ?? false,
        ],
    }),

    loaders(({ actions, props, values }) => ({
        action: [
            { ...props.action } as ActionType,
            {
                setAction: ({ action, options: { merge } }) =>
                    (merge ? { ...values.action, ...action } : action) as ActionType,
            },
        ],
        migration: [
            true,
            {
                migrateToHogFunction: async () => {
                    if (props.id) {
                        const hogFunction = await api.actions.migrate(props.id)
                        actions.setActionValues({ post_to_slack: false })
                        actions.loadActions()
                        if (hogFunctionListLogic.isMounted()) {
                            hogFunctionListLogic.actions.addHogFunction(hogFunction)
                        }
                        if (actionLogic({ id: props.id }).isMounted()) {
                            actionLogic({ id: props.id }).actions.loadAction()
                        }
                        lemonToast.success('Action migrated to a destination!')
                    }
                    return true
                },
            },
        ],
    })),

    listeners(({ values, actions }) => ({
        deleteAction: async () => {
            const actionId = values.action.id
            if (!actionId) {
                return
            }
            try {
                await deleteWithUndo({
                    endpoint: api.actions.determineDeleteEndpoint(),
                    object: values.action,
                    callback: (undo: boolean) => {
                        if (undo) {
                            router.actions.push(urls.action(actionId))
                        } else {
                            actions.resetAction()
                            router.actions.push(urls.actions())
                            actions.loadActions()
                        }
                    },
                })
            } catch (e: any) {
                lemonToast.error(`Error deleting action: ${e.detail}`)
            }
        },
    })),

    afterMount(({ actions, props }) => {
        if (!props.id) {
            actions.setActionValue('steps', [{ ...DEFAULT_ACTION_STEP }])
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
                            steps: actionToCopy.steps,
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

    beforeUnload(({ actions, values }) => ({
        enabled: () => values.actionChanged,
        message: 'Leave action?\nChanges you made will be discarded.',
        onConfirm: () => {
            actions.resetAction()
        },
    })),
])
