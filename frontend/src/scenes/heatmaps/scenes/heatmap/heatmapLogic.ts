import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { heatmapsBrowserLogic } from 'scenes/heatmaps/components/heatmapsBrowserLogic'
import { heatmapsSceneLogic } from 'scenes/heatmaps/scenes/heatmaps/heatmapsSceneLogic'

import { HeatmapStatus, HeatmapType } from '~/types'

import type { heatmapLogicType } from './heatmapLogicType'

export const heatmapLogic = kea<heatmapLogicType>([
    path(['scenes', 'heatmaps', 'scenes', 'heatmap', 'heatmapLogic']),
    props({ id: 'new' as string | number }),
    key((props) => props.id),
    connect(() => ({
        values: [heatmapsBrowserLogic, ['dataUrl', 'displayUrl', 'isBrowserUrlAuthorized', 'widthOverride']],
        actions: [
            heatmapsBrowserLogic,
            ['setDataUrl', 'setDisplayUrl', 'onIframeLoad'],
            heatmapsSceneLogic,
            ['loadSavedHeatmaps'],
            heatmapDataLogic,
            ['loadHeatmap'],
        ],
    })),
    actions({
        load: true,
        createHeatmap: true,
        updateHeatmap: true,
        setLoading: (loading: boolean) => ({ loading }),
        setType: (type: HeatmapType) => ({ type }),
        setWidth: (width: number) => ({ width }),
        setName: (name: string) => ({ name }),
        setScreenshotUrl: (url: string | null) => ({ url }),
        setScreenshotError: (error: string | null) => ({ error }),
        pollScreenshotStatus: (id: number) => ({ id }),
    }),
    reducers({
        type: ['screenshot' as HeatmapType, { setType: (_, { type }) => type }],
        width: [1024 as number | null, { setWidth: (_, { width }) => width }],
        name: ['New heatmap', { setName: (_, { name }) => name }],
        loading: [false, { setLoading: (_, { loading }) => loading }],
        status: ['processing' as HeatmapStatus, { setStatus: (_, { status }) => status }],
        screenshotUrl: [null as string | null, { setScreenshotUrl: (_, { url }) => url }],
        screenshotError: [null as string | null, { setScreenshotError: (_, { error }) => error }],
        generatingScreenshot: [false, { setLoading: (state, { loading }) => (loading ? state : state) }],
        // expose a screenshotLoading alias for UI compatibility
        screenshotLoading: [false as boolean, { setScreenshotUrl: () => false }],
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
                    if (item.status === 'completed' && item.has_content) {
                        actions.setScreenshotUrl(
                            `/api/environments/${window.POSTHOG_APP_CONTEXT?.current_team?.id}/heatmap_screenshots/${item.id}/content/`
                        )
                        // trigger heatmap overlay load
                        actions.loadHeatmap()
                    } else if (item.status === 'failed') {
                        actions.setScreenshotError(item.exception || 'Screenshot generation failed')
                    } else {
                        actions.setScreenshotError(null)
                        actions.pollScreenshotStatus(item.id)
                    }
                }
            } finally {
                actions.setLoading(false)
            }
        },
        pollScreenshotStatus: async ({ id }, breakpoint) => {
            let attempts = 0
            const maxAttempts = 30
            while (attempts < maxAttempts) {
                await breakpoint(1000)
                try {
                    const contentResponse = await api.heatmapScreenshots.getContent(id)
                    if (contentResponse.success) {
                        actions.setScreenshotUrl(
                            `/api/environments/${window.POSTHOG_APP_CONTEXT?.current_team?.id}/heatmap_screenshots/${id}/content/`
                        )
                        actions.loadHeatmap()
                        break
                    } else {
                        const screenshot = contentResponse.data
                        if (screenshot.status === 'completed' && screenshot.has_content) {
                            actions.setScreenshotUrl(
                                `/api/environments/${window.POSTHOG_APP_CONTEXT?.current_team?.id}/heatmap_screenshots/${screenshot.id}/content/`
                            )
                            actions.loadHeatmap()
                            break
                        } else if (screenshot.status === 'failed') {
                            actions.setScreenshotError(
                                screenshot.exception || (screenshot as any).error || 'Screenshot generation failed'
                            )
                            break
                        }
                    }
                    attempts++
                } catch (e) {
                    actions.setScreenshotError('Failed to check screenshot status')
                    console.error(e)
                    break
                }
            }
            if (attempts >= maxAttempts) {
                actions.setScreenshotError('Screenshot generation timed out')
            }
        },
        createHeatmap: async () => {
            actions.setLoading(true)
            try {
                const data = {
                    name: values.name,
                    url: values.displayUrl,
                    data_url: values.displayUrl,
                    width: values.width,
                    type: values.type,
                }
                const created = await api.heatmapSaved.create(data)
                actions.loadSavedHeatmaps()
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
