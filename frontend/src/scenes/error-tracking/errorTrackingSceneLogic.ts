import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'

import { DataTableNode, ErrorTrackingQuery } from '~/queries/schema'

import { errorTrackingLogic } from './errorTrackingLogic'
import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'
import { errorTrackingQuery } from './queries'

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSceneLogic']),

    connect({
        values: [
            errorTrackingLogic,
            ['dateRange', 'assignee', 'filterTestAccounts', 'filterGroup', 'sparklineSelectedPeriod', 'searchQuery'],
        ],
    }),

    actions({
        setOrder: (order: ErrorTrackingQuery['order']) => ({ order }),
        setIsConfigurationModalOpen: (open: boolean) => ({ open }),
        setSelectedRowIndexes: (ids: number[]) => ({ ids }),
    }),
    reducers({
        order: [
            'last_seen' as ErrorTrackingQuery['order'],
            { persist: true },
            {
                setOrder: (_, { order }) => order,
            },
        ],
        isConfigurationModalOpen: [
            false as boolean,
            {
                setIsConfigurationModalOpen: (_, { open }) => open,
            },
        ],
        selectedRowIndexes: [
            [] as number[],
            {
                setSelectedRowIndexes: (_, { ids }) => ids,
            },
        ],
    }),

    selectors({
        query: [
            (s) => [
                s.order,
                s.dateRange,
                s.assignee,
                s.filterTestAccounts,
                s.filterGroup,
                s.sparklineSelectedPeriod,
                s.searchQuery,
            ],
            (
                order,
                dateRange,
                assignee,
                filterTestAccounts,
                filterGroup,
                sparklineSelectedPeriod,
                searchQuery
            ): DataTableNode =>
                errorTrackingQuery({
                    order,
                    dateRange,
                    assignee,
                    filterTestAccounts,
                    filterGroup,
                    sparklineSelectedPeriod,
                    searchQuery,
                }),
        ],
    }),

    subscriptions(({ actions }) => ({
        query: () => actions.setSelectedRowIndexes([]),
    })),

    forms(({ actions }) => ({
        uploadSourceMap: {
            defaults: { files: [] } as { files: File[] },
            submit: async ({ files }) => {
                if (files.length > 0) {
                    const formData = new FormData()
                    const file = files[0]
                    formData.append('source_map', file)
                    await api.errorTracking.uploadSourceMaps(formData)
                    actions.setIsConfigurationModalOpen(false)
                    lemonToast.success('Source map uploaded')
                }
            },
        },
    })),
])
