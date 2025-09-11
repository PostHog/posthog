import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { urls } from 'scenes/urls'

import { deleteFromTree, getLastNewFolder, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { actionsModel } from '~/models/actionsModel'
import { tagsModel } from '~/models/tagsModel'
import { ActionStepType, ActionType } from '~/types'

import type { actionEditLogicType } from './actionEditLogicType'
import { actionLogic } from './actionLogic'

export interface SetActionProps {
    merge?: boolean
}

export interface ActionEditLogicProps {
    id: number
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
    connect(() => ({
        actions: [
            actionsModel,
            ['loadActions'],
            eventDefinitionsTableLogic,
            ['loadEventDefinitions'],
            tagsModel,
            ['loadTags'],
        ],
    })),
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
                    _create_in_folder: null,
                } as ActionType),
            submit: async (updatedAction, breakpoint) => {
                let action: ActionType
                // Remove URL from steps if it's not an autocapture or a pageview
                let updatedSteps = updatedAction.steps
                if (updatedSteps !== undefined) {
                    updatedSteps = updatedSteps.map((step: ActionStepType) => ({
                        ...step,
                        ...(step.event === '$autocapture' || step.event === '$pageview'
                            ? {}
                            : { url: null, url_matching: null }),
                    }))
                }
                try {
                    if (updatedAction.id) {
                        action = await api.actions.update(updatedAction.id, { ...updatedAction, steps: updatedSteps })
                    } else {
                        const folder = updatedAction._create_in_folder ?? getLastNewFolder()
                        action = await api.actions.create({
                            ...updatedAction,
                            steps: updatedSteps,
                            ...(typeof folder === 'string' ? { _create_in_folder: folder } : {}),
                        })
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
                refreshTreeItem('action', String(action.id))
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
            (action) =>
                action?.steps?.some((step: ActionStepType) => step.properties?.find((p: any) => p.type === 'cohort')) ??
                false,
        ],
        originalActionHasCohortFilters: [
            () => [(_, p: ActionEditLogicProps) => p.action],
            (action) =>
                action?.steps?.some((step: ActionStepType) => step.properties?.find((p: any) => p.type === 'cohort')) ??
                false,
        ],
        showCohortDisablesFunctionsWarning: [
            (s) => [s.hasCohortFilters, s.originalActionHasCohortFilters],
            (hasCohortFilters, originalActionHasCohortFilters) => hasCohortFilters && !originalActionHasCohortFilters,
        ],
    }),

    loaders(({ props, values }) => ({
        action: [
            { ...props.action } as ActionType,
            {
                setAction: ({ action, options: { merge } }) =>
                    (merge ? { ...values.action, ...action } : action) as ActionType,
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
                            refreshTreeItem('action', String(actionId))
                        } else {
                            actions.resetAction()
                            deleteFromTree('action', String(actionId))
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
        } else if (props.action) {
            // Sync the prop action with the internal state when mounting with an existing action
            actions.setAction(props.action, { merge: false })
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
            } catch {
                throw new Error('Could not parse action to copy from URL')
            }
        },
    })),

    beforeUnload((logic) => ({
        enabled: () => (logic.isMounted() ? logic.values.actionChanged : false),
        message: 'Leave action?\nChanges you made will be discarded.',
        onConfirm: () => {
            logic.actions.resetAction()
        },
    })),
])
