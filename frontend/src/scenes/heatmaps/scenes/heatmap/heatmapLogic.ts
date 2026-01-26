import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { DEFAULT_HEATMAP_WIDTH } from 'lib/components/IframedToolbarBrowser/utils'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { heatmapsBrowserLogic } from 'scenes/heatmaps/components/heatmapsBrowserLogic'
import { heatmapsSceneLogic } from 'scenes/heatmaps/scenes/heatmaps/heatmapsSceneLogic'

import { HeatmapStatus, HeatmapType } from '~/types'

import type { heatmapLogicType } from './heatmapLogicType'

export const heatmapLogic = kea<heatmapLogicType>([
    path(['scenes', 'heatmaps', 'scenes', 'heatmap', 'heatmapLogic']),
    props({ id: 'new' as string | number }),
    key((props) => props.id),
    connect(() => ({
        values: [
            heatmapsBrowserLogic,
            ['dataUrl', 'displayUrl', 'isBrowserUrlAuthorized'],
            heatmapDataLogic({ context: 'in-app' }),
            [
                'heatmapFilters',
                'heatmapColorPalette',
                'heatmapFixedPositionMode',
                'commonFilters',
                'widthOverride',
                'heightOverride',
            ],
        ],
        actions: [
            heatmapsBrowserLogic,
            ['setDataUrl', 'setDisplayUrl', 'onIframeLoad'],
            heatmapsSceneLogic,
            ['loadSavedHeatmaps'],
            heatmapDataLogic({ context: 'in-app' }),
            ['loadHeatmap', 'setWindowWidthOverride'],
            exportsLogic,
            ['startHeatmapExport'],
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
        setGeneratingScreenshot: (generating: boolean) => ({ generating }),
        pollScreenshotStatus: (id: number, width?: number) => ({ id, width }),
        setHeatmapId: (id: number | null) => ({ id }),
        setScreenshotLoaded: (screenshotLoaded: boolean) => ({ screenshotLoaded }),
        exportHeatmap: true,
        setContainerWidth: (containerWidth: number | null) => ({ containerWidth }),
        setImageUrl: (imageUrl: string | null) => ({ imageUrl }),
        setImageWidth: (imageWidth: number | null) => ({ imageWidth }),
        setUploadedImageWidth: (uploadedImageWidth: number | null) => ({ uploadedImageWidth }),
    }),
    reducers({
        type: ['screenshot' as HeatmapType, { setType: (_, { type }) => type }],
        width: [DEFAULT_HEATMAP_WIDTH as number | null, { setWidth: (_, { width }) => width }],
        name: ['New heatmap', { setName: (_, { name }) => name }],
        loading: [false, { setLoading: (_, { loading }) => loading }],
        status: ['processing' as HeatmapStatus, { setStatus: (_, { status }) => status }],
        screenshotUrl: [null as string | null, { setScreenshotUrl: (_, { url }) => url }],
        screenshotError: [null as string | null, { setScreenshotError: (_, { error }) => error }],
        generatingScreenshot: [false, { setGeneratingScreenshot: (_, { generating }) => generating }],
        // expose a screenshotLoading alias for UI compatibility
        screenshotLoading: [false as boolean, { setScreenshotUrl: () => false }],
        heatmapId: [null as number | null, { setHeatmapId: (_, { id }) => id }],
        screenshotLoaded: [false, { setScreenshotLoaded: (_, { screenshotLoaded }) => screenshotLoaded }],
        containerWidth: [null as number | null, { setContainerWidth: (_, { containerWidth }) => containerWidth }],
        imageUrl: [null as string | null, { setImageUrl: (_, { imageUrl }) => imageUrl }],
        imageWidth: [null as number | null, { setImageWidth: (_, { imageWidth }) => imageWidth }],
        // Width captured at runtime via onLoad (used for display scaling)
        uploadedImageWidth: [
            null as number | null,
            { setUploadedImageWidth: (_, { uploadedImageWidth }) => uploadedImageWidth },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        load: async () => {
            if (!props.id || String(props.id) === 'new') {
                return
            }
            actions.setLoading(true)
            try {
                const item = await api.savedHeatmaps.get(props.id)
                actions.setHeatmapId(item.id)
                actions.setName(item.name)
                actions.setDisplayUrl(item.url)
                actions.setDataUrl(item.data_url)
                actions.setType(item.type)
                if (item.type === 'screenshot') {
                    const desiredWidth = values.widthOverride
                    if (item.status === 'completed' && item.has_content) {
                        actions.setScreenshotUrl(
                            `/api/environments/${window.POSTHOG_APP_CONTEXT?.current_team?.id}/heatmap_screenshots/${item.id}/content/?width=${desiredWidth}`
                        )
                        // trigger heatmap overlay load
                        actions.loadHeatmap()
                    } else if (item.status === 'failed') {
                        actions.setScreenshotError(item.exception || 'Screenshot generation failed')
                    } else {
                        actions.setScreenshotError(null)
                        actions.pollScreenshotStatus(item.id, desiredWidth)
                    }
                } else if (item.type === 'upload') {
                    if (item.image_url) {
                        actions.setImageUrl(item.image_url)
                        // Width will be captured via onLoad in HeatmapScene
                        actions.loadHeatmap()
                    }
                }
            } finally {
                actions.setLoading(false)
            }
        },
        // React to viewport width changes by updating the image URL directly
        setWindowWidthOverride: async ({ widthOverride }) => {
            if (values.type !== 'screenshot' || !values.heatmapId) {
                return
            }
            const w = widthOverride ?? DEFAULT_HEATMAP_WIDTH
            actions.setScreenshotError(null)
            actions.setScreenshotUrl(
                `/api/environments/${window.POSTHOG_APP_CONTEXT?.current_team?.id}/heatmap_screenshots/${values.heatmapId}/content/?width=${w}`
            )
        },
        pollScreenshotStatus: async ({ id, width }, breakpoint) => {
            let attempts = 0
            actions.setGeneratingScreenshot(true)
            const maxAttempts = 60
            while (attempts < maxAttempts) {
                await breakpoint(2000)
                try {
                    const contentResponse = await api.heatmapScreenshots.getContent(id)
                    if (contentResponse.success) {
                        const w = width ?? DEFAULT_HEATMAP_WIDTH
                        actions.setScreenshotUrl(
                            `/api/environments/${window.POSTHOG_APP_CONTEXT?.current_team?.id}/heatmap_screenshots/${id}/content/?width=${w}`
                        )
                        actions.loadHeatmap()
                        actions.setGeneratingScreenshot(false)
                        break
                    } else {
                        const screenshot = contentResponse.data
                        if (screenshot.status === 'completed' && screenshot.has_content) {
                            const w = width ?? DEFAULT_HEATMAP_WIDTH
                            actions.setScreenshotUrl(
                                `/api/environments/${window.POSTHOG_APP_CONTEXT?.current_team?.id}/heatmap_screenshots/${screenshot.id}/content/?width=${w}`
                            )
                            actions.loadHeatmap()
                            actions.setGeneratingScreenshot(false)
                            break
                        } else if (screenshot.status === 'failed') {
                            actions.setScreenshotError(
                                screenshot.exception || (screenshot as any).error || 'Screenshot generation failed'
                            )
                            actions.setGeneratingScreenshot(false)
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
                const data: {
                    name: string
                    url: string
                    data_url: string | null
                    type: HeatmapType
                    image_url?: string | null
                } = {
                    name: values.name,
                    url: values.displayUrl || '',
                    data_url: values.dataUrl,
                    type: values.type,
                }
                if (values.type === 'upload' && values.imageUrl) {
                    data.image_url = values.imageUrl
                }
                const created = await api.savedHeatmaps.create(data)
                actions.loadSavedHeatmaps()
                // Navigate to the created heatmap detail page
                router.actions.push(`/heatmaps/${created.short_id}`)
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to create heatmap')
            } finally {
                actions.setLoading(false)
            }
        },
        updateHeatmap: async () => {
            actions.setLoading(true)
            try {
                const data = {
                    name: values.name,
                    url: values.displayUrl || '',
                    data_url: values.dataUrl,
                    type: values.type,
                    image_url: values.type === 'upload' ? values.imageUrl : null,
                }
                await api.savedHeatmaps.update(props.id, data)
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to update heatmap')
            } finally {
                actions.setLoading(false)
            }
        },
        exportHeatmap: () => {
            if (
                (values.type === 'screenshot' && !values.screenshotUrl) ||
                (values.type === 'upload' && !values.imageUrl) ||
                (!values.displayUrl && !values.dataUrl)
            ) {
                return
            }
            const heatmapUrl =
                values.type === 'screenshot'
                    ? (values.screenshotUrl ?? '')
                    : values.type === 'upload'
                      ? (values.imageUrl ?? '')
                      : (values.displayUrl ?? '')
            actions.startHeatmapExport({
                heatmap_url: heatmapUrl,
                heatmap_data_url: values.dataUrl ?? '',
                heatmap_type: values.type,
                width: values.type === 'upload' ? values.uploadedImageWidth : values.widthOverride,
                heatmap_color_palette: values.heatmapColorPalette,
                heatmap_fixed_position_mode: values.heatmapFixedPositionMode,
                common_filters: values.commonFilters,
                heatmap_filters: values.heatmapFilters,
                filename: `heatmap-${values.name}-${dayjs().format('YYYY-MM-DD-HH-mm')}`,
            })
        },
    })),
    selectors({
        isDisplayUrlValid: [
            (s) => [s.displayUrl],
            (displayUrl: string | null) => {
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
        desiredNumericWidth: [
            (s) => [s.widthOverride, s.containerWidth],
            (widthOverride: number, containerWidth: number | null) => {
                return containerWidth ? Math.min(widthOverride, containerWidth) : widthOverride
            },
        ],
        effectiveWidth: [(s) => [s.desiredNumericWidth], (desiredNumericWidth: number) => desiredNumericWidth],
        scalePercent: [
            (s) => [s.widthOverride, s.containerWidth],
            (widthOverride: number, containerWidth: number | null) => {
                const scale = containerWidth ? Math.min(1, containerWidth / widthOverride) : 1
                return Math.round(scale * 100)
            },
        ],
        // For upload type: effective width is min of image natural width and container
        uploadEffectiveWidth: [
            (s) => [s.uploadedImageWidth, s.containerWidth],
            (uploadedImageWidth: number | null, containerWidth: number | null) => {
                if (!uploadedImageWidth) {
                    return null
                }
                return containerWidth ? Math.min(uploadedImageWidth, containerWidth) : uploadedImageWidth
            },
        ],
        uploadScalePercent: [
            (s) => [s.uploadedImageWidth, s.containerWidth],
            (uploadedImageWidth: number | null, containerWidth: number | null) => {
                if (!uploadedImageWidth || !containerWidth) {
                    return 100
                }
                const scale = Math.min(1, containerWidth / uploadedImageWidth)
                return Math.round(scale * 100)
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.load()
    }),
])
