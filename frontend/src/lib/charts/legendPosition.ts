import type { ChartLegendConfig } from '@posthog/quill-charts'

import { PIE_DISPLAY_TYPES } from 'lib/constants'

import type { LegendPosition } from '~/queries/schema/schema-general'
import type { ChartDisplayType } from '~/types'

/** The legend box's position for a saved `legendPosition`. `surrounding` labels a pie's slices instead
 *  of drawing a box, so any other chart, such as a pie switched to a line chart, reads it as unset and
 *  keeps its own default. */
export function legendBoxPosition(position: string | null | undefined): ChartLegendConfig['position'] | undefined {
    return position == null || position === 'surrounding' ? undefined : (position as ChartLegendConfig['position'])
}

/** Exports pin the legend to the bottom to match the legacy exported layout. A pie or donut saved with
 *  surrounding labels keeps them, because they name the slices in the exported image too. */
export function exportedLegendPosition(
    savedPosition: string | null | undefined,
    display: ChartDisplayType | null | undefined
): LegendPosition {
    return savedPosition === 'surrounding' && !!display && PIE_DISPLAY_TYPES.includes(display)
        ? 'surrounding'
        : 'bottom'
}
