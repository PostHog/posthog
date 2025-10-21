import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { heatmapsBrowserLogic } from 'scenes/heatmaps/components/heatmapsBrowserLogic'

import { HeatmapStatus, HeatmapType } from '~/types'

import type { heatmapLogicType } from './heatmapLogicType'

export const heatmapLogic = kea<heatmapLogicType>([
    path(['scenes', 'heatmaps', 'scenes', 'heatmap', 'heatmapLogic']),
    props({ id: null as string | number | null }),
    connect(() => ({
        values: [
            heatmapsBrowserLogic,
            [
                'dataUrl',
                'displayUrl',
                'isBrowserUrlAuthorized',
                'widthOverride',
                'screenshotUrl',
                'screenshotLoading',
                'generatingScreenshot',
            ],
        ],
        actions: [heatmapsBrowserLogic, ['setDataUrl', 'setDisplayUrl', 'onIframeLoad', 'generateScreenshot']],
    })),
    actions({
        load: true,
        createHeatmap: true,
        updateHeatmap: true,
        setLoading: (loading: boolean) => ({ loading }),
        setType: (type: HeatmapType) => ({ type }),
        setWidth: (width: number) => ({ width }),
        setName: (name: string) => ({ name }),
    }),
    reducers({
        type: ['screenshot' as HeatmapType, { setType: (_, { type }) => type }],
        width: [1024 as number | null, { setWidth: (_, { width }) => width }],
        name: ['New heatmap', { setName: (_, { name }) => name }],
        loading: [false, { setLoading: (_, { loading }) => loading }],
        status: ['processing' as HeatmapStatus, { setStatus: (_, { status }) => status }],
    }),
    listeners(({ actions, values, props }) => ({
        load: async () => {
            if (!props.id || String(props.id) === 'new') {
                return
            }
            actions.setLoading(true)
            try {
                const item = await api.heatmapSaved.get(props.id)
                actions.setName(item.name)
                actions.setDisplayUrl(item.url)
                actions.setDataUrl(item.data_url)
                actions.setWidth(item.width)
                actions.setType(item.type)
                if (item.type === 'screenshot') {
                    actions.generateScreenshot()
                }
            } finally {
                actions.setLoading(false)
            }
        },
        createHeatmap: async () => {
            actions.setLoading(true)
            try {
                const data = {
                    name: values.name,
                    url: values.displayUrl,
                    data_url: values.dataUrl,
                    width: values.width,
                    type: values.type,
                }
                const created = await api.heatmapSaved.create(data)
                // Navigate to the created heatmap detail page
                router.actions.push(`/heatmaps/${created.short_id}`)
            } finally {
                actions.setLoading(false)
            }
        },
        updateHeatmap: async () => {
            actions.setLoading(true)
            try {
                const data = {
                    name: values.name,
                    url: values.displayUrl,
                    data_url: values.dataUrl,
                    width: values.width,
                    type: values.type,
                }
                const updated = await api.heatmapSaved.update(props.id, data)
                actions.setHeatmap(updated)
            } finally {
                actions.setLoading(false)
            }
        },
    })),
    selectors({
        isDisplayUrlValid: [
            (s) => [s.displayUrl],
            (displayUrl) => {
                if (!displayUrl) {
                    // an empty dataUrl is valid
                    // since we just won't do anything with it
                    return true
                }

                try {
                    // must be something that can be parsed as a URL
                    new URL(displayUrl)
                    // and must be a valid URL that our redirects can cope with
                    // this is a very loose check, but `http:/blaj` is not valid for PostHog
                    // but survives new URL(http:/blaj)
                    return displayUrl.includes('://')
                } catch {
                    return false
                }
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.load()
    }),
])
