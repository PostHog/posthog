import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router, urlToAction } from 'kea-router'
import { CombinedLocation } from 'kea-router/lib/utils'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { deleteFromTree, getLastNewFolder, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { actionsModel } from '~/models/actionsModel'
import { tagsModel } from '~/models/tagsModel'
import { ActionStepType, ActionType } from '~/types'

import type { ActionReferenceApi } from '../generated/api.schemas'
import { deleteActionWithWarning } from '../utils/deleteAction'
import type { actionEditLogicType } from './actionEditLogicType'
import { actionLogic } from './actionLogic'

export const REFERENCE_TYPE_LABELS: Record<string, string> = {
    insight: 'Insight',
    experiment: 'Experiment',
    cohort: 'Cohort',
    hog_function: 'Destination',
}

export interface SetActionProps {
    merge?: boolean
}

export interface ActionEditLogicProps {
    id: number
    action?: ActionType | null
    tabId?: string
}

export const DEFAULT_ACTION_STEP: ActionStepType = {
    event: '$pageview',
    href_matching: 'contains',
}

export const actionEditLogic = kea<actionEditLogicType>([
    path((key) => ['scenes', 'actions', 'actionEditLogic', key]),
    props({} as ActionEditLogicProps),
    // Key by tabId AND id so each tab preserves its own form state across tab switches.
    // Fall back to 'notab' for non-scene mounts (e.g. tests, side panel) to stay backwards-compatible.
    key((props) => `${props.tabId || 'notab'}:${props.id || 'new'}`),
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
        setReferencesSearch: (search: string) => ({ search }),
        setOriginalAction: (action: ActionType | null) => ({ action }),
    }),
    reducers(({ props }) => ({
        createNew: [
            false,
            {
                setCreateNew: (_, { createNew }) => createNew,
            },
        ],
        referencesSearch: [
            '',
            {
                setReferencesSearch: (_, { search }) => search,
            },
        ],
        // originalAction mirrors the action at the time it was first loaded, so edits can be
        // compared against it (e.g. to detect cohort filter additions). It is stored as a
        // reducer rather than derived from props because the logic may outlive the initial
        // props.action (e.g. when the logic is mounted eagerly by the scene logic before the
        // action has loaded).
        originalAction: [
            (props.action ?? null) as ActionType | null,
            {
                setOriginalAction: (_, { action }) => action,
            },
        ],
    })),
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
                    if (response.code === 'blank' && response.attr === 'name') {
                        lemonToast.error('Action name cannot be empty.')
                        return { ...updatedAction }
                    }
                    throw response
                }

                lemonToast.success(`Action saved`)
                actions.resetAction(updatedAction)
                actions.setOriginalAction(action)
                refreshTreeItem('action', String(action.id))
                if (!props.id) {
                    // Mark task complete when creating a new action
                    globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.DefineActions)
                    router.actions.push(urls.action(action.id))
                } else {
                    const id = parseInt(props.id.toString()) // props.id can be a string
                    const logic = actionLogic.findMounted({ tabId: props.tabId, id })
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
            (s) => [s.originalAction],
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
        references: [
            [] as ActionReferenceApi[],
            {
                loadReferences: async () => {
                    if (!props.id) {
                        return []
                    }
                    const response = await api.get(`api/projects/@current/actions/${props.id}/references`)
                    return response
                },
            },
        ],
    })),

    selectors({
        analyticsReferences: [
            (s) => [s.references],
            (references: ActionReferenceApi[]): ActionReferenceApi[] =>
                references.filter((ref) => ref.type !== 'hog_function'),
        ],
        filteredReferences: [
            (s) => [s.analyticsReferences, s.referencesSearch],
            (references: ActionReferenceApi[], search: string): ActionReferenceApi[] => {
                if (!search) {
                    return references
                }
                const lower = search.toLowerCase()
                return references.filter(
                    (ref) =>
                        ref.name.toLowerCase().includes(lower) ||
                        (REFERENCE_TYPE_LABELS[ref.type] ?? ref.type).toLowerCase().includes(lower)
                )
            },
        ],
    }),

    listeners(({ values, actions }) => ({
        deleteAction: async () => {
            const actionId = values.action.id
            if (!actionId) {
                return
            }

            await deleteActionWithWarning(values.action, (undo: boolean) => {
                if (undo) {
                    router.actions.push(urls.action(actionId))
                    refreshTreeItem('action', String(actionId))
                } else {
                    actions.resetAction()
                    deleteFromTree('action', String(actionId))
                    router.actions.push(urls.actions())
                    actions.loadActions()
                }
            })
        },
    })),

    afterMount(({ actions, props }) => {
        if (!props.id) {
            actions.setActionValue('steps', [{ ...DEFAULT_ACTION_STEP }])
        } else {
            if (props.action) {
                // Sync the prop action with the internal state when mounting with an existing action
                actions.setAction(props.action, { merge: false })
                actions.setOriginalAction(props.action)
            }
            actions.loadReferences()
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
        enabled: (newLocation?: CombinedLocation) => {
            if (!logic.isMounted() || !logic.values.actionChanged) {
                return false
            }

            // Ignore in-page URL updates such as opening the side panel
            if (newLocation && newLocation.pathname === router.values.location.pathname) {
                return false
            }

            // Skip the prompt for tab switches — our tab still exists, the logic stays mounted
            // via the scene-logic cache, and the form state is preserved. A tab switch shows up
            // in one of two ways at beforeUnload time:
            //  - switching AWAY: sceneLogic.activateTab() has already moved active to another
            //    tab before router.push fires, so activeTabId !== our tabId.
            //  - switching BACK: active is now us again, and the push target is our own tab's
            //    stored pathname.
            // Anything else (in-tab navigation, closing our tab) should still prompt.
            const myTabId = logic.props.tabId
            const scene = sceneLogic.findMounted()
            if (myTabId && scene && newLocation) {
                const myTab = scene.values.tabs.find((t) => t.id === myTabId)
                if (myTab) {
                    if (scene.values.activeTabId !== myTabId) {
                        return false
                    }
                    if (myTab.pathname === newLocation.pathname) {
                        return false
                    }
                }
            }

            return true
        },
        message: 'Leave action?\nChanges you made will be discarded.',
        onConfirm: () => {
            logic.actions.resetAction()
        },
    })),
])
