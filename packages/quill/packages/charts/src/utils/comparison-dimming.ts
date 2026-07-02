import type { Series } from '../core/types'
import { hexToRGBA } from './format'

/** Alpha applied to subordinate series (comparison periods and trend-line overlays) so they read
 *  as secondary to their primary. Shared with `buildTrendLineSeries` via {@link dimHex}. */
export const DIM_OPACITY = 0.5

/** Re-render comparison series at reduced opacity so they read as subordinate to their
 *  primary. Series whose colour is missing or already an `rgba(...)` string are left as-is
 *  — `hexToRGBA` only handles hex inputs. */
export function applyComparisonDimming<Meta = unknown>(
    series: Series<Meta>[],
    comparisonOf: Record<string, string> | undefined
): Series<Meta>[] {
    if (!comparisonOf || Object.keys(comparisonOf).length === 0) {
        return series
    }
    return series.map((s) => {
        if (!(s.key in comparisonOf)) {
            return s
        }
        const dimmed = dimHex(s.color, DIM_OPACITY)
        return dimmed === s.color ? s : { ...s, color: dimmed }
    })
}

/** Apply alpha dimming to a hex colour. Returns the input unchanged for non-hex inputs
 *  (CSS variables, `rgba(...)`, undefined) since `hexToRGBA` only handles hex. */
export function dimHex(color: string | undefined, alpha: number): string | undefined {
    if (!color || !color.startsWith('#')) {
        return color
    }
    return hexToRGBA(color, alpha)
}
