import { actions, afterMount, kea, listeners, path, props, reducers } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'

import { HeatmapScreenshotType } from '~/types'

import type { heatmapLogicType } from './heatmapLogicType'

export const heatmapLogic = kea<heatmapLogicType>([
    path(['scenes', 'heatmaps', 'heatmapLogic']),
    props({ id: null as string | number | null }),
    actions({
        load: true,
        create: (data: {
            url: string
            data_url?: string | null
            width?: number
            type?: 'screenshot' | 'iframe' | 'recording'
        }) => ({ data }),
        setHeatmap: (heatmap: HeatmapScreenshotType | null) => ({ heatmap }),
        setLoading: (loading: boolean) => ({ loading }),
    }),
    reducers({
        heatmap: [null as HeatmapScreenshotType | null, { setHeatmap: (_, { heatmap }) => heatmap }],
        loading: [false, { setLoading: (_, { loading }) => loading }],
    }),
    listeners(({ actions, props }) => ({
        load: async () => {
            if (!props.id || String(props.id) === 'new') {
                return
            }
            actions.setLoading(true)
            try {
                const item = await api.heatmapSaved.get(props.id)
                actions.setHeatmap(item)
            } finally {
                actions.setLoading(false)
            }
        },
        create: async ({ data }) => {
            actions.setLoading(true)
            try {
                const created = await api.heatmapSaved.create(data)
                actions.setHeatmap(created)
                // Navigate to the created heatmap detail page
                router.actions.push(`/heatmaps/${created.id}`)
            } finally {
                actions.setLoading(false)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.load()
    }),
])
