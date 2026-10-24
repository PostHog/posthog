import type { HogChart } from './accessor'

const PAINT_STATE_ATTRIBUTE = 'data-hog-charts-paint'

export interface StaticRepaintTracker {
    /** Static-canvas repaints requested since tracking started. */
    count(): number
    stop(): void
}

/** Counts repaints of a chart's static (data) canvas from now on, read from its
 *  `data-hog-charts-paint` marker. Use it to assert that an interaction, such as hover, repaints
 *  only the hover canvas. */
export function trackStaticRepaints(chart: HogChart): StaticRepaintTracker {
    const { canvas } = chart
    let repaints = 0
    const observer = new MutationObserver(() => {})
    observer.observe(canvas, { attributes: true, attributeFilter: [PAINT_STATE_ATTRIBUTE], attributeOldValue: true })
    const drain = (): void => {
        const records = observer.takeRecords()
        records.forEach((record, i) => {
            // A record holds only the old value; the new one is the next record's old value.
            const newValue =
                i + 1 < records.length ? records[i + 1].oldValue : canvas.getAttribute(PAINT_STATE_ATTRIBUTE)
            if (newValue === 'pending' && record.oldValue !== 'pending') {
                repaints++
            }
        })
    }
    return {
        count: () => {
            drain()
            return repaints
        },
        stop: () => {
            drain()
            observer.disconnect()
        },
    }
}
