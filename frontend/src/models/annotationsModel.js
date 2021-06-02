import { kea } from 'kea'
import api from 'lib/api'
import { toParams, deleteWithUndo } from 'lib/utils'
import dayjs from 'dayjs'
import { insightDataCachingLogic } from 'lib/logic/insightDataCachingLogic'

const endpoint = 'api/annotation/?' + toParams({ scope: 'organization', deleted: false })

export const annotationsModel = kea({
    connect: {
        actions: [insightDataCachingLogic, ['maybeLoadData', 'refreshData']],
        values: [insightDataCachingLogic, ['cachedData', 'cacheLoading']],
    },
    actions: () => ({
        createGlobalAnnotation: (content, date_marker, dashboard_item) => ({
            content,
            date_marker,
            created_at: dayjs(),
            dashboard_item,
        }),
        deleteGlobalAnnotation: (id) => ({ id }),
    }),
    selectors: ({ selectors }) => ({
        globalAnnotations: [
            (s) => [s.cachedData],
            (cachedData) => (cachedData['globalAnnotations'] ? cachedData['globalAnnotations'].results : []),
        ],
        activeGlobalAnnotations: [
            () => [selectors.globalAnnotations],
            (globalAnnotations) => {
                return globalAnnotations.filter((annotation) => !annotation.deleted)
            },
        ],
    }),
    listeners: ({ actions }) => ({
        createGlobalAnnotation: async ({ dashboard_item, content, date_marker, created_at }) => {
            await api.create('api/annotation', {
                content,
                date_marker: dayjs.isDayjs(date_marker) ? date_marker : dayjs(date_marker),
                created_at,
                dashboard_item,
                scope: 'organization',
            })
            actions.refreshData({ key: 'globalAnnotations', endpoint })
        },
        deleteGlobalAnnotation: async ({ id }) => {
            id >= 0 &&
                deleteWithUndo({
                    endpoint: 'annotation',
                    object: { name: 'Annotation', id },
                    callback: () => actions.refreshData({ key: 'globalAnnotations', endpoint }),
                })
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.maybeLoadData({ key: 'globalAnnotations', endpoint })
        },
    }),
})
