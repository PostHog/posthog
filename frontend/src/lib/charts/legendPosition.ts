import type { ChartLegendConfig } from '@posthog/quill-charts'

import { PIE_DISPLAY_TYPES } from 'lib/constants'

import type { LegendPosition } from '~/queries/schema/schema-general'
import type { ChartDisplayType } from '~/types'

/** Other charts read the pie-only `surrounding` as unset, so they keep their own default. */
export function legendBoxPosition(position: string | null | undefined): ChartLegendConfig['position'] | undefined {
    return position == null || position === 'surrounding' ? undefined : (position as ChartLegendConfig['position'])
}

export function exportedLegendPosition(
    savedPosition: string | null | undefined,
    display: ChartDisplayType | null | undefined
): LegendPosition {
    return savedPosition === 'surrounding' && !!display && PIE_DISPLAY_TYPES.includes(display)
        ? 'surrounding'
        : 'bottom'
}
