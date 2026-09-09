import { useCallback } from 'react'

import type { ChartLegendConfig } from '@posthog/quill-charts'

import { captureLegendMenuAction } from './captureLegendMenuAction'
import { ChartLegendSeriesMenu } from './ChartLegendSeriesMenu'

interface UseChartLegendSeriesMenuOptions {
    /** Which chart the legend belongs to, e.g. 'trends' or 'sql'. Reported with the menu's events. */
    surface: string
    seriesCount: number
}

/** Attaches {@link ChartLegendSeriesMenu} to every row of a quill chart's built-in legend. Pass the
 *  result as `config.legend.renderItem` — quill hands each row its own visibility state and actions,
 *  so this works the same on a controlled legend (trends, persisting into the query) and an
 *  uncontrolled one (SQL insights, in-chart state). */
export function useChartLegendSeriesMenu({
    surface,
    seriesCount,
}: UseChartLegendSeriesMenuOptions): NonNullable<ChartLegendConfig['renderItem']> {
    return useCallback(
        (node, item, controls) => (
            <ChartLegendSeriesMenu
                seriesLabel={item.label}
                seriesColor={item.color}
                isHidden={controls.isHidden}
                isOnlyVisible={controls.isOnlyVisible}
                areAllVisible={controls.areAllVisible}
                canIsolate={controls.canIsolate}
                showGestureHints
                onToggle={() => {
                    captureLegendMenuAction({
                        action: controls.isHidden ? 'show_series' : 'hide_series',
                        source: 'toggle_row',
                        surface,
                        seriesCount,
                    })
                    controls.toggle()
                }}
                onIsolate={() => {
                    captureLegendMenuAction({
                        action: controls.isOnlyVisible ? 'show_all_series' : 'hide_other_series',
                        source: 'isolate_row',
                        surface,
                        seriesCount,
                    })
                    controls.isolate()
                }}
                onToggleAll={() => {
                    captureLegendMenuAction({
                        action: controls.areAllVisible ? 'hide_all_series' : 'show_all_series',
                        source: 'toggle_all_row',
                        surface,
                        seriesCount,
                    })
                    controls.toggleAll()
                }}
            >
                {node}
            </ChartLegendSeriesMenu>
        ),
        [surface, seriesCount]
    )
}
