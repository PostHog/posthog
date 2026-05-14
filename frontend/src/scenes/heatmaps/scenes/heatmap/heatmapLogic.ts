import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { DEFAULT_HEATMAP_WIDTH } from 'lib/components/IframedToolbarBrowser/utils'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { heatmapsBrowserLogic, isUrlPattern } from 'scenes/heatmaps/components/heatmapsBrowserLogic'
import { heatmapsSceneLogic } from 'scenes/heatmaps/scenes/heatmaps/heatmapsSceneLogic'

import { HeatmapStatus, HeatmapType } from '~/types'

import type { heatmapLogicType } from './heatmapLogicType'

const DEFAULT_HEATMAP_NAME = 'Untitled heatmap'

function isValidPageUrl(url: string | null): boolean {
    if (!url) {
        return true
    }
    if (isUrlPattern(url)) {
        return false
    }
    try {
        new URL(url)
        return url.includes('://')
    } catch {
        return false
    }
}

// Screenshot heatmaps store a same-origin API path as `screenshotUrl`; the export backend's
// SSRF validation rejects URLs without an http(s) scheme, so we resolve it to an absolute URL.
export function resolveHeatmapExportUrl(
    type: HeatmapType,
    screenshotUrl: string | null,
    displayUrl: string | null,
    origin: string = window.location.origin
): string {
    if (type === 'screenshot') {
        return screenshotUrl ? new URL(screenshotUrl, origin).toString() : ''
    }
    return displayUrl ?? ''
}

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
            ['setDataUrl', 'setDisplayUrl', 'onIframeLoad', 'setDataUrlUserTouched'],
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
        changeCaptureMethod: (type: HeatmapType) => ({ type }),
        setWidth: (width: number) => ({ width }),
        setName: (name: string) => ({ name }),
        setScreenshotUrl: (url: string | null) => ({ url }),
        setScreenshotError: (error: string | null) => ({ error }),
        setGeneratingScreenshot: (generating: boolean) => ({ generating }),
        pollScreenshotStatus: (id: number, width?: number) => ({ id, width }),
        setHeatmapId: (id: number | null) => ({ id }),
        setScreenshotLoaded: (screenshotLoaded: boolean) => ({ screenshotLoaded }),
        regenerateScreenshot: true,
        exportHeatmap: true,
        setContainerWidth: (containerWidth: number | null) => ({ containerWidth }),
        snapshotSavedDisplayUrl: (displayUrl: string | null) => ({ displayUrl }),
        setPageUrlDraft: (value: string) => ({ value }),
        applyPageUrlDraft: true,
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
        savedDisplayUrl: [null as string | null, { snapshotSavedDisplayUrl: (_, { displayUrl }) => displayUrl }],
        pageUrlDraft: [
            '' as string,
            {
                setPageUrlDraft: (_, { value }) => value,
                setDisplayUrl: (_, { url }) => url ?? '',
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        changeCaptureMethod: async ({ type }) => {
            actions.setType(type)
            if (!values.heatmapId) {
                return
            }
            await actions.updateHeatmap()
            if (type === 'screenshot' && !values.screenshotUrl) {
                actions.regenerateScreenshot()
            }
        },
        load: async () => {
            if (!props.id || String(props.id) === 'new') {
                return
            }
            actions.setLoading(true)
            try {
                const item = await api.savedHeatmaps.get(props.id)
                actions.setHeatmapId(item.id)
                actions.setName(item.name)
                actions.setDataUrlUserTouched(true)
                actions.setDisplayUrl(item.url)
                actions.setDataUrl(item.data_url)
                actions.snapshotSavedDisplayUrl(item.url ?? null)
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
                actions.setGeneratingScreenshot(false)
                actions.setScreenshotError('Screenshot generation timed out')
            }
        },
        regenerateScreenshot: async () => {
            if (!props.id || !values.heatmapId) {
                return
            }
            actions.setScreenshotError(null)
            actions.setScreenshotUrl(null)
            actions.setScreenshotLoaded(false)
            try {
                await api.savedHeatmaps.regenerate(props.id)
                actions.pollScreenshotStatus(values.heatmapId, values.widthOverride)
            } catch (error: any) {
                actions.setScreenshotError(error.detail || 'Failed to regenerate screenshot')
            }
        },
        createHeatmap: async () => {
            actions.setLoading(true)
            try {
                const data = {
                    name: values.name || DEFAULT_HEATMAP_NAME,
                    url: values.displayUrl || '',
                    data_url: values.dataUrl,
                    type: values.type,
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
            const previousSavedUrl = values.savedDisplayUrl
            try {
                const data = {
                    name: values.name || DEFAULT_HEATMAP_NAME,
                    url: values.displayUrl || '',
                    data_url: values.dataUrl,
                    type: values.type,
                }
                const updated = await api.savedHeatmaps.update(props.id, data)
                actions.snapshotSavedDisplayUrl(updated.url ?? null)
                if (values.type === 'screenshot' && updated.url !== previousSavedUrl) {
                    actions.setScreenshotUrl(null)
                    actions.setScreenshotLoaded(false)
                    actions.setScreenshotError(null)
                    if (values.heatmapId) {
                        actions.pollScreenshotStatus(values.heatmapId, values.widthOverride)
                    }
                }
            } catch (error: any) {
                if (values.displayUrl !== previousSavedUrl) {
                    actions.setDisplayUrl(previousSavedUrl)
                }
                lemonToast.error(error.detail || 'Failed to update heatmap')
            } finally {
                actions.setLoading(false)
            }
        },
        applyPageUrlDraft: () => {
            if (!values.isPageUrlDraftValid) {
                return
            }
            const next = values.pageUrlDraft.trim()
            if (!next) {
                return
            }
            if (next !== values.displayUrl) {
                actions.setDisplayUrl(next)
                actions.updateHeatmap()
                return
            }
            if (values.type === 'screenshot') {
                actions.regenerateScreenshot()
            }
        },
        exportHeatmap: () => {
            if ((values.type === 'screenshot' && !values.screenshotUrl) || (!values.displayUrl && !values.dataUrl)) {
                return
            }
            actions.startHeatmapExport({
                heatmap_url: resolveHeatmapExportUrl(values.type, values.screenshotUrl, values.displayUrl),
                heatmap_data_url: values.dataUrl ?? '',
                heatmap_type: values.type,
                width: values.widthOverride,
                heatmap_color_palette: values.heatmapColorPalette,
                heatmap_fixed_position_mode: values.heatmapFixedPositionMode,
                common_filters: values.commonFilters,
                heatmap_filters: values.heatmapFilters,
                filename: `heatmap-${values.name || DEFAULT_HEATMAP_NAME}-${dayjs().format('YYYY-MM-DD-HH-mm')}`,
            })
        },
    })),
    selectors({
        isDisplayUrlValid: [(s) => [s.displayUrl], (displayUrl: string | null) => isValidPageUrl(displayUrl)],
        displayUrlIsPattern: [(s) => [s.displayUrl], (displayUrl: string | null) => isUrlPattern(displayUrl ?? '')],
        isPageUrlDraftValid: [
            (s) => [s.pageUrlDraft],
            (pageUrlDraft: string) => isValidPageUrl(pageUrlDraft.trim() || null),
        ],
        pageUrlDraftIsPattern: [(s) => [s.pageUrlDraft], (pageUrlDraft: string) => isUrlPattern(pageUrlDraft)],
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
    }),
    afterMount(({ actions }) => {
        actions.load()
    }),
])
