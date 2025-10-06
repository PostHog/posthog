import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DataManagementTab } from 'scenes/data-management/DataManagementScene'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActionStepType, ActionType, ActivityScope, Breadcrumb, HogFunctionType, ProjectTreeRef } from '~/types'

import { actionEditLogic } from './actionEditLogic'
import type { actionLogicType } from './actionLogicType'

export interface ActionLogicProps {
    id: ActionType['id']
}

export const actionLogic = kea<actionLogicType>([
    props({} as ActionLogicProps),
    key((props) => props.id || 'new'),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    path((key) => ['scenes', 'actions', 'actionLogic', key]),
    actions(() => ({
        updateAction: (action: Partial<ActionType>) => ({ action }),
        checkIsFinished: (action) => ({ action }),
        setPollTimeout: (pollTimeout) => ({ pollTimeout }),
        setIsComplete: (isComplete) => ({ isComplete }),
    })),
    loaders(({ props }) => ({
        action: [
            null as ActionType | null,
            {
                loadAction: async () => {
                    if (!props.id) {
                        throw new Error('Cannot fetch an unsaved action from the API.')
                    }
                    return await api.actions.get(props.id)
                },
            },
        ],
        matchingHogFunctions: [
            null as HogFunctionType[] | null,
            {
                loadMatchingHogFunctions: async () => {
                    const res = await api.hogFunctions.list({
                        filter_groups: [{ actions: [{ id: `${props.id}`, type: 'actions' }] }],
                    })

                    return res.results
                },
            },
        ],
    })),
    reducers(() => ({
        action: [
            null as ActionType | null,
            {
                updateAction: (state, { action }) => (state ? { ...state, ...action } : null),
            },
        ],
        pollTimeout: [
            null as number | null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
        isComplete: [
            false as boolean,
            {
                setIsComplete: (_, { isComplete }) => isComplete,
            },
        ],
    })),
    selectors({
        projectTreeRef: [(_, p) => [p.id], (id): ProjectTreeRef => ({ type: 'action', ref: String(id) })],
        hasCohortFilters: [
            (s) => [s.action],
            (action) =>
                action?.steps?.some((step: ActionStepType) => step.properties?.find((p: any) => p.type === 'cohort')) ??
                false,
        ],

        breadcrumbs: [
            (s) => [
                s.action,
                (state, props) =>
                    actionEditLogic.findMounted(String(props?.id || 'new'))?.selectors.action(state).name || null,
            ],
            (action, inProgressName): Breadcrumb[] => [
                {
                    key: DataManagementTab.Actions,
                    name: 'Actions',
                    path: urls.actions(),
                    iconType: 'action',
                },
                {
                    key: [Scene.Action, action?.id || 'new'],
                    name: inProgressName ?? (action?.name || ''),
                    forceEditMode: !action?.id,
                    iconType: 'action',
                },
            ],
        ],

        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.action],
            (action): SidePanelSceneContext | null => {
                return action?.id
                    ? {
                          activity_scope: ActivityScope.ACTION,
                          activity_item_id: `${action.id}`,
                          //   access_control_resource: 'action',
                          //   access_control_resource_id: `${action.id}`,
                      }
                    : null
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        checkIsFinished: ({ action }) => {
            if (action.is_calculating) {
                actions.setPollTimeout(setTimeout(() => actions.loadAction(), 1000))
            } else {
                actions.setIsComplete(new Date())
                values.pollTimeout && clearTimeout(values.pollTimeout)
            }
        },
        loadActionSuccess: ({ action }) => {
            actions.setIsComplete(false)
            actions.checkIsFinished(action)
        },
    })),
    events(({ values, actions, props }) => ({
        afterMount: () => {
            props.id && actions.loadAction()
        },
        beforeUnmount: () => {
            values.pollTimeout && clearTimeout(values.pollTimeout)
        },
    })),
])
