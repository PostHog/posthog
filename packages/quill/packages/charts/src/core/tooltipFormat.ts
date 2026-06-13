/** Placeholder shown for a value that has no meaningful number — a gap point on a line
 *  (NaN) or a non-finite result. Tooltips render this instead of "NaN"/"Infinity". */
export const TOOLTIP_EMPTY_VALUE = '—'

/** Format a series value for a tooltip, guarding non-finite values (NaN, ±Infinity) so gap
 *  points read as an em dash rather than "NaN". `formatter` defaults to locale-grouped number
 *  formatting; the chart engine passes the y-axis tick formatter so tooltip and axis agree. */
export function formatTooltipValue(value: number, formatter?: (value: number) => string): string {
    if (!Number.isFinite(value)) {
        return TOOLTIP_EMPTY_VALUE
    }
    return formatter ? formatter(value) : value.toLocaleString()
}
