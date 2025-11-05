import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'

import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { isUrlPattern } from 'scenes/heatmaps/components/heatmapsBrowserLogic'

import type { exporterViewLogicType } from './exporterViewLogicType'
import { ExportType, ExportedData } from './types'

// This is a simple logic that is mounted by the Exporter view and then can be found by any nested callers
// This simplifies passing props everywhere.
// E.g. api.ts uses this to add the sharing_access_token
export const exporterViewLogic = kea<exporterViewLogicType>([
    path(['exporter', 'exporterViewLogic']),
    props({} as ExportedData),
    connect((props: ExportedData) => ({
        actions: [
            heatmapDataLogic({ context: 'in-app', exportToken: props.exportToken }),
            [
                'setHref',
                'setHrefMatchType',
                'setHeatmapFilters',
                'setHeatmapFixedPositionMode',
                'setHeatmapColorPalette',
                'setCommonFilters',
            ],
        ],
    })),
    actions({
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setScreenshotUrl: (screenshotUrl: string) => ({ screenshotUrl }),
        fetchScreenshotUrl: true,
    }),
    reducers({
        isLoading: [false, { setIsLoading: (_, { isLoading }) => isLoading }],
        screenshotUrl: [null as string | null, { setScreenshotUrl: (_, { screenshotUrl }) => screenshotUrl }],
    }),
    selectors({
        exportedData: [() => [(_, props: ExportedData) => props], (props: ExportedData) => props],
    }),
    listeners(({ actions, props }) => ({
        fetchScreenshotUrl: async () => {
            if (props.heatmap_context?.heatmap_type !== 'screenshot') {
                return
            }
            actions.setIsLoading(true)
            try {
                const response = await fetch(props.heatmap_url ?? '', {
                    headers: { Authorization: `Bearer ${props.exportToken}` },
                })
                if (response.ok) {
                    const blob = await response.blob()
                    const objectUrl = URL.createObjectURL(blob)
                    actions.setScreenshotUrl(objectUrl)
                } else {
                    console.error('Failed to fetch screenshot:', response.status)
                }
            } catch (error) {
                console.error('Failed to fetch screenshot:', error)
            } finally {
                actions.setIsLoading(false)
            }
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.type === ExportType.Heatmap && props.heatmap_url) {
            if (props.heatmap_context?.heatmap_type === 'screenshot') {
                actions.fetchScreenshotUrl()
            } else {
                actions.setIsLoading(false)
            }
            if (props.heatmap_context?.heatmap_data_url) {
                actions.setHref(props.heatmap_context?.heatmap_data_url)
                if (isUrlPattern(props.heatmap_context?.heatmap_data_url)) {
                    actions.setHrefMatchType('pattern')
                } else {
                    actions.setHrefMatchType('exact')
                }
            }

            if (props.heatmap_context?.heatmap_filters) {
                actions.setHeatmapFilters(props.heatmap_context.heatmap_filters)
            }
            if (props.heatmap_context?.heatmap_fixed_position_mode) {
                actions.setHeatmapFixedPositionMode(props.heatmap_context.heatmap_fixed_position_mode)
            }
            if (props.heatmap_context?.heatmap_color_palette) {
                actions.setHeatmapColorPalette(props.heatmap_context.heatmap_color_palette)
            }
            if (props.heatmap_context?.common_filters) {
                actions.setCommonFilters(props.heatmap_context.common_filters)
            }
        }
    }),
])

export const getCurrentExporterData = (): ExportedData | undefined => {
    return exporterViewLogic.findMounted()?.values.exportedData
}
