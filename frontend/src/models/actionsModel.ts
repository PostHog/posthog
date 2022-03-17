import { kea } from 'kea'
import api from 'lib/api'
import { ActionType } from '~/types'
import { actionsModelType } from './actionsModelType'
import { router } from 'kea-router'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

interface ActionsModelProps {
    params?: string
}

export function findActionName(id: number): string | null {
    return actionsModel.findMounted()?.values.actions.find((a) => a.id === id)?.name || null
}

export const actionsModel = kea<actionsModelType<ActionsModelProps>>({
    path: ['models', 'actionsModel'],
    props: {} as ActionsModelProps,
    loaders: ({ props, values, cache }) => ({
        actions: {
            __default: [] as ActionType[],
            loadActions: async () => {
                cache.startTime = performance.now()
                const response = await api.actions.list(props.params)
                return response.results ?? []
            },
            updateAction: (action: ActionType) => (values.actions || []).map((a) => (action.id === a.id ? action : a)),
        },
    }),
    listeners: ({ cache, values }) => ({
        loadActionsSuccess: () => {
            if (cache.startTime !== undefined && router.values.location.pathname.startsWith('/data-management/')) {
                eventUsageLogic
                    .findMounted()
                    ?.actions.reportDataManagementActionDefinitionsPageViewed(
                        performance.now() - cache.startTime,
                        values.actions.length
                    )
                cache.startTime = undefined
            }
        },
        loadActionsFailure: ({ error }) => {
            if (cache.startTime !== undefined && router.values.location.pathname.startsWith('/data-management/')) {
                eventUsageLogic
                    .findMounted()
                    ?.actions.reportDataManagementActionDefinitionsPageViewed(
                        performance.now() - cache.startTime,
                        -1,
                        error
                    )
                cache.startTime = undefined
            }
        },
    }),
    selectors: ({ selectors }) => ({
        actionsGrouped: [
            () => [selectors.actions],
            (actions: ActionType[]) => {
                return [
                    {
                        label: 'Select an action',
                        options: actions.map((action) => {
                            return { label: action.name, value: action.id }
                        }),
                    },
                ]
            },
        ],
    }),

    events: ({ actions }) => ({
        afterMount: () => actions.loadActions(),
    }),
})
