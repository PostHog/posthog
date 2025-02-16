import { IconCollapse } from '@posthog/icons'
import clsx from 'clsx'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { HeatmapsSettings } from 'lib/components/heatmaps/HeatMapsSettings'
import { CommonFilters, HeatmapFilters, HeatmapFixedPositionMode } from 'lib/components/heatmaps/types'
import { heatmapDateOptions } from 'lib/components/IframedToolbarBrowser/utils'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

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
}): JSX.Element {
    return (
        <div className={clsx('flex flex-col gap-y-2 px-2 py-1 border-r', !filterPanelCollapsed && 'w-100')}>
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
                    {loading && <LoadingBar />}
                    <DateFilter
                        dateFrom={commonFilters?.date_from}
                        dateTo={commonFilters?.date_to}
                        onChange={(fromDate, toDate) => {
                            setCommonFilters?.({ date_from: fromDate, date_to: toDate })
                        }}
                        dateOptions={heatmapDateOptions}
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
