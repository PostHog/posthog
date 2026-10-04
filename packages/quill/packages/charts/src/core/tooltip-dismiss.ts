/** Chart tooltips render through a floating portal on `document.body`, outside the chart's own
 *  DOM subtree. A host that hides or replaces a page without unmounting the chart — a router
 *  swap, a suspended scene — therefore leaves the tooltip on screen over the next page. The host
 *  calls `dismissChartTooltips()` at those moments; every mounted chart clears its tooltip. */
export const HOG_CHARTS_DISMISS_TOOLTIPS_EVENT = 'hog-charts:dismiss-tooltips'

export function dismissChartTooltips(): void {
    document.dispatchEvent(new Event(HOG_CHARTS_DISMISS_TOOLTIPS_EVENT))
}
