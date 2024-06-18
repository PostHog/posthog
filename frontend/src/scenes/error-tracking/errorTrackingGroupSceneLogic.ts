import { afterMount, connect, kea, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, EventType } from '~/types'

import type { errorTrackingGroupSceneLogicType } from './errorTrackingGroupSceneLogicType'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingGroupQuery } from './queries'

export interface ErrorTrackingGroupSceneLogicProps {
    id: string
}

export type ExceptionEventType = Pick<EventType, 'properties' | 'timestamp' | 'person'>

export const errorTrackingGroupSceneLogic = kea<errorTrackingGroupSceneLogicType>([
    path((key) => ['scenes', 'error-tracking', 'errorTrackingGroupSceneLogic', key]),
    props({} as ErrorTrackingGroupSceneLogicProps),

    connect({
        values: [errorTrackingLogic, ['dateRange', 'filterTestAccounts', 'filterGroup']],
    }),

    loaders(({ props, values }) => ({
        events: [
            [] as ExceptionEventType[],
            {
                loadEvents: async () => {
                    const response = await api.query(
                        errorTrackingGroupQuery({
                            group: props.id,
                            dateRange: values.dateRange,
                            filterTestAccounts: values.filterTestAccounts,
                            filterGroup: values.filterGroup,
                        })
                    )

                    return response.results.map((r) => ({
                        properties: JSON.parse(r[0]),
                        timestamp: r[1],
                        person: r[2],
                    }))
                },
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            (_, p) => [p.id],
            (id): Breadcrumb[] => {
                return [
                    {
                        key: Scene.ErrorTracking,
                        name: 'Error tracking',
                        path: urls.errorTracking(),
                    },
                    {
                        key: [Scene.ErrorTrackingGroup, id],
                        name: id,
                    },
                ]
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadEvents()
    }),
])
