import { kea } from 'kea'
import { insightDataCachingLogic } from 'lib/logic/insightDataCachingLogic'
import { ActionType } from '~/types'
import { actionsModelType } from './actionsModelType'

export const actionsModel = kea<actionsModelType<ActionType>>({
    connect: {
        actions: [insightDataCachingLogic, ['maybeLoadData', 'refreshData']],
        values: [insightDataCachingLogic, ['cachedData', 'cacheLoading']],
    },

    actions: {
        loadActions: true,
    },

    // @ts-ignore
    selectors: ({ props }) => ({
        endpoint: [
            // Kea.js bug - for some reason removing `s.cachedData` from first selector causes selectors to go missing from types
            (s) => [s.cachedData],
            () => `api/action/?${props.params ? props.params : ''}`,
        ],
        actions: [
            (s) => [s.cachedData, s.endpoint],
            (cachedData, endpoint): ActionType[] => cachedData[endpoint]?.results || [],
        ],
        actionsLoading: [
            (s) => [s.cacheLoading, s.endpoint],
            (cacheLoading, endpoint): boolean => !!cacheLoading[endpoint],
        ],
        actionsGrouped: [
            (s) => [s.actions],
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

    listeners: ({ values, actions }) => ({
        loadActions: () => {
            actions.refreshData({
                key: values.endpoint,
                endpoint: values.endpoint,
            })
        },
    }),

    events: ({ values, actions }) => ({
        afterMount: () => {
            actions.maybeLoadData({
                key: values.endpoint,
                endpoint: values.endpoint,
            })
        },
    }),
})
