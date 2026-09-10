import { useValues } from 'kea'

import { HEATMAP_LOADING_DEBOUNCE_MS, heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

export function HeatmapLoadingInfo({
    context,
    exportToken,
}: {
    context: 'in-app' | 'toolbar'
    exportToken?: string
}): JSX.Element | null {
    const { rawHeatmapLoading } = useValues(heatmapDataLogic({ context, exportToken }))
    const loading = useDebouncedValue(rawHeatmapLoading, HEATMAP_LOADING_DEBOUNCE_MS)

    if (!loading || context === 'toolbar' || exportToken || inStorybook() || inStorybookTestRunner()) {
        return null
    }

    return (
        <div className="absolute inset-0 z-20 flex items-start justify-center pointer-events-none">
            <div className="flex items-center gap-2 mt-8 px-3 py-2 border rounded bg-surface-primary shadow-md font-semibold">
                <Spinner />
                Loading heatmap data
            </div>
        </div>
    )
}
