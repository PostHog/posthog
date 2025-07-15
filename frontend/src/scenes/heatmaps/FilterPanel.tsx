import { IconCollapse } from '@posthog/icons'
import clsx from 'clsx'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { HeatmapsSettings } from 'lib/components/heatmaps/HeatMapsSettings'
import { CommonFilters, HeatmapFilters, HeatmapFixedPositionMode } from 'lib/components/heatmaps/types'
import { heatmapDateOptions } from 'lib/components/IframedToolbarBrowser/utils'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useEffect, useState } from 'react'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

const useDebounceLoading = (loading: boolean, delay = 200): boolean => {
    const [debouncedLoading, setDebouncedLoading] = useState(false)

    useEffect(() => {
        const timer = setTimeout(() => {
            setDebouncedLoading(loading)
        }, delay)

        return () => clearTimeout(timer)
    }, [loading, delay])

    return debouncedLoading
}

/**
 * values and actions are passed as props because they are different
 * between fixed and embedded mode
 */
export function FilterPanel({
    heatmapFilters,
    heatmapColorPalette,
    heatmapFixedPositionMode,
    viewportRange,
    commonFilters,
    filterPanelCollapsed,
    loading,
    patchHeatmapFilters,
    setHeatmapColorPalette,
    setHeatmapFixedPositionMode,
    setCommonFilters,
    toggleFilterPanelCollapsed,
    isEmpty,
}: {
    heatmapFilters?: HeatmapFilters
    heatmapColorPalette?: string | null
    heatmapFixedPositionMode?: HeatmapFixedPositionMode
    viewportRange?: { max: number; min: number }
    commonFilters?: CommonFilters
    filterPanelCollapsed?: boolean
    loading?: boolean
    patchHeatmapFilters?: (filters: Partial<HeatmapFilters>) => void
    setHeatmapColorPalette?: (palette: string | null) => void
    setHeatmapFixedPositionMode?: (mode: HeatmapFixedPositionMode) => void
    setCommonFilters?: (filters: CommonFilters) => void
    toggleFilterPanelCollapsed?: () => void
    isEmpty?: boolean
}): JSX.Element {
    const debouncedLoading = useDebounceLoading(loading ?? false)

    return (
        <div
            className={clsx(
                'flex flex-col gap-y-2 px-2 py-1 border-r border-t bg-surface-primary mt-2 relative',
                !filterPanelCollapsed && 'w-100'
            )}
        >
            {debouncedLoading && (
                <LoadingBar
                    wrapperClassName="absolute top-0 left-0 w-full overflow-hidden rounded-none my-0"
                    className="h-1 rounded-none"
                />
            )}
            {filterPanelCollapsed ? (
                <Tooltip title="Expand heatmap settings">
                    <LemonButton
                        size="small"
                        icon={<IconChevronRight />}
                        onClick={() => toggleFilterPanelCollapsed?.()}
                    />
                </Tooltip>
            ) : (
                <>
                    <div className="flex flex-row items-center">
                        <Tooltip title="Collapse heatmap settings">
                            <LemonButton
                                size="small"
                                icon={<IconCollapse className="rotate-90" />}
                                onClick={() => toggleFilterPanelCollapsed?.()}
                            />
                        </Tooltip>
                        <h2 className="flex-1 mb-0 px-2">Heatmap settings</h2>
                    </div>
                    {isEmpty ? (
                        <LemonBanner type="info">
                            No data found. Try changing your filters or the URL above.
                        </LemonBanner>
                    ) : null}
                    <DateFilter
                        dateFrom={commonFilters?.date_from}
                        dateTo={commonFilters?.date_to}
                        onChange={(fromDate, toDate) => {
                            setCommonFilters?.({ ...commonFilters, date_from: fromDate, date_to: toDate })
                        }}
                        dateOptions={heatmapDateOptions}
                    />
                    <TestAccountFilter
                        filters={{ filter_test_accounts: commonFilters?.filter_test_accounts }}
                        onChange={(value) => {
                            setCommonFilters?.({
                                ...commonFilters,
                                filter_test_accounts: value.filter_test_accounts,
                            })
                        }}
                    />
                    <HeatmapsSettings
                        heatmapFilters={heatmapFilters}
                        patchHeatmapFilters={patchHeatmapFilters}
                        viewportRange={viewportRange}
                        heatmapColorPalette={heatmapColorPalette}
                        setHeatmapColorPalette={setHeatmapColorPalette}
                        heatmapFixedPositionMode={heatmapFixedPositionMode}
                        setHeatmapFixedPositionMode={setHeatmapFixedPositionMode}
                    />
                </>
            )}
        </div>
    )
}
