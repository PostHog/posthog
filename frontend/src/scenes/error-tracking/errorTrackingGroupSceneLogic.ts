import { afterMount, kea, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { uuid } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { HogQLQuery, NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'
import { Breadcrumb, ErrorTrackingGroup, EventType } from '~/types'

import type { errorTrackingGroupSceneLogicType } from './errorTrackingGroupSceneLogicType'

export interface ErrorTrackingGroupSceneLogicProps {
    id: ErrorTrackingGroup['id']
}

export const errorTrackingGroupSceneLogic = kea<errorTrackingGroupSceneLogicType>([
    path((key) => ['scenes', 'error-tracking', 'errorTrackingGroupSceneLogic', key]),
    props({} as ErrorTrackingGroupSceneLogicProps),

    loaders(({ props }) => ({
        group: [
            null as ErrorTrackingGroup | null,
            {
                loadGroup: async () => {
                    // TODO: properly flesh out this page
                    return {
                        id: uuid(),
                        title: 'Placeholder title',
                        description: 'This is an error message',
                        occurrences: 0,
                        uniqueSessions: 0,
                        uniqueUsers: 0,
                    }
                },
            },
        ],
        eventProperties: [
            [] as EventType['properties'][],
            {
                loadGroupEvents: async () => {
                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: hogql`SELECT properties
                                FROM events e
                                WHERE event = '$exception' AND properties.$exception_type = '${props.id}'`,
                    }
                    const res = await api.query(query)
                    return res.results.map((r) => JSON.parse(r[0]))
                },
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            (s) => [s.group],
            (group): Breadcrumb[] => {
                return [
                    {
                        key: Scene.ErrorTracking,
                        name: 'Error tracking',
                        path: urls.errorTracking(),
                    },
                    {
                        key: [Scene.ErrorTrackingGroup, group?.id || 'unknown'],
                        name: group?.title,
                    },
                ]
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadGroup()
        actions.loadGroupEvents()
    }),
])
