/** An x position shared between the charts of a `ChartGroup`. */
export interface ChartGroupX {
    /** The label under the pointer on the chart that published it. */
    label: string
    /** Epoch milliseconds when the label is an ISO date or date-time, otherwise null. */
    time: number | null
    /** Epoch milliseconds of the end of that label's bucket (exclusive), when it is known. */
    end?: number | null
}

/** An x range shared between the charts of a `ChartGroup`, from a drag-to-zoom or a brush. */
export interface ChartGroupRange {
    /** First label of the range, on the chart where the user dragged. */
    startLabel: string
    /** Last label of the range (inclusive), on the chart where the user dragged. */
    endLabel: string
    /** Epoch milliseconds of the start of the first bucket. Null on a categorical axis. */
    from: number | null
    /** Epoch milliseconds of the end of the last bucket (exclusive), so `[from, to)` covers every
     *  dragged bucket in full. Null on a categorical axis. */
    to: number | null
}

/** Precomputed lookup that maps group x values onto one chart's labels. Build it once per label set. */
export interface ChartGroupXIndex {
    labels: string[]
    /** First index of each label. Empty on a time axis, which matches by time instead. */
    byLabel: Map<string, number>
    /** Ascending epoch milliseconds per label, or null when the labels are not all ISO times. */
    times: number[] | null
    /** Typical bucket width (median gap between labels). 0 when there are fewer than two labels. */
    step: number
}

// Calendar months and DST days make buckets uneven, so a gap only counts as missing data once it
// is clearly wider than the typical bucket.
const GAP_TOLERANCE = 1.5

const ISO_DATE_TIME = /^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$/

/** Parses an ISO 8601 date or date-time label to epoch milliseconds, or returns null.
 *  A label without an offset reads as UTC, so `2024-01-01` and `2024-01-01T00:00:00` agree. */
export function parseGroupTime(label: string): number | null {
    const match = ISO_DATE_TIME.exec(label)
    if (!match) {
        return null
    }
    const hasTime = label.length > 10
    const offset = match[1]
    let normalized = label.replace(' ', 'T')
    if (hasTime && !offset) {
        normalized += 'Z'
    } else if (offset && offset.length === 5) {
        // `Date.parse` only guarantees the `+HH:MM` offset form, so `+HHMM` gains its colon.
        normalized = `${normalized.slice(0, -2)}:${normalized.slice(-2)}`
    }
    const time = Date.parse(normalized)
    return Number.isFinite(time) ? time : null
}

function median(values: number[]): number {
    const sorted = [...values].sort((a, b) => a - b)
    const mid = sorted.length >> 1
    return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

function parseAscendingTimes(labels: string[]): number[] | null {
    if (labels.length === 0) {
        return null
    }
    const times: number[] = new Array(labels.length)
    for (let i = 0; i < labels.length; i++) {
        const time = parseGroupTime(labels[i])
        if (time == null || (i > 0 && time <= times[i - 1])) {
            return null
        }
        times[i] = time
    }
    return times
}

export function buildChartGroupXIndex(labels: string[]): ChartGroupXIndex {
    const times = parseAscendingTimes(labels)
    const byLabel = new Map<string, number>()
    if (!times) {
        for (let i = 0; i < labels.length; i++) {
            if (!byLabel.has(labels[i])) {
                byLabel.set(labels[i], i)
            }
        }
    }
    const step = times && times.length > 1 ? median(times.slice(1).map((t, i) => t - times[i])) : 0
    return { labels, byLabel, times, step }
}

/** End (exclusive) of the bucket that starts at `index`: the next label, or one typical bucket
 *  when missing data follows, so the gap does not stretch the bucket before it. */
function bucketEnd(index: ChartGroupXIndex, i: number): number {
    const times = index.times as number[]
    const start = times[i]
    if (index.step === 0) {
        return start
    }
    const next = i + 1 < times.length ? times[i + 1] : Infinity
    const gapBeforeNext = next - start > index.step * GAP_TOLERANCE
    return gapBeforeNext ? start + index.step : next
}

/** End (exclusive) of the bucket at `i` in epoch milliseconds, or null on a categorical axis or a
 *  single-label chart, where the bucket width is unknown. */
export function chartGroupEndAt(index: ChartGroupXIndex, i: number): number | null {
    return index.times && index.step > 0 && i >= 0 && i < index.times.length ? bucketEnd(index, i) : null
}

/** The group x value of this chart's label at `i`. */
export function chartGroupXAt(index: ChartGroupXIndex, i: number): ChartGroupX | null {
    const label = index.labels[i]
    if (label == null) {
        return null
    }
    if (!index.times) {
        return { label, time: null }
    }
    return { label, time: index.times[i], end: chartGroupEndAt(index, i) }
}

/** Maps a group x value onto this chart's labels. Returns -1 when nothing here matches it.
 *
 *  - Both sides are times: the bucket that contains the time, where a label marks the start of its
 *    bucket. When no bucket contains it (before the first, after the last, inside a gap), the first
 *    label inside the publishing chart's bucket, so a coarse hover still finds a finer chart's point.
 *    Otherwise nothing matches.
 *  - Otherwise: the label with the same string. */
export function matchChartGroupX(index: ChartGroupXIndex, x: ChartGroupX): number {
    const { times } = index
    if (times == null || x.time == null) {
        return index.byLabel.get(x.label) ?? -1
    }
    const t = x.time
    if (t < times[0]) {
        return firstLabelInside(times, t, x.end)
    }
    let lo = 0
    let hi = times.length - 1
    while (lo < hi) {
        const mid = (lo + hi + 1) >> 1
        if (times[mid] <= t) {
            lo = mid
        } else {
            hi = mid - 1
        }
    }
    if (t === times[lo]) {
        return lo
    }
    if (t < bucketEnd(index, lo)) {
        return lo
    }
    return lo + 1 < times.length ? firstLabelInside(times, t, x.end, lo + 1) : -1
}

/** A chart with a single point, or a gap under the pointer, has no bucket that contains the time.
 *  Fall back to a label that sits inside the publishing chart's own bucket. */
function firstLabelInside(times: number[], start: number, end: number | null | undefined, from = 0): number {
    if (end == null) {
        return -1
    }
    for (let i = from; i < times.length && times[i] < end; i++) {
        if (times[i] >= start) {
            return i
        }
    }
    return -1
}

/** The group range covered by this chart's labels `startIndex..endIndex` (inclusive). */
export function chartGroupRangeAt(index: ChartGroupXIndex, startIndex: number, endIndex: number): ChartGroupRange {
    const lo = Math.max(0, Math.min(startIndex, endIndex))
    const hi = Math.min(index.labels.length - 1, Math.max(startIndex, endIndex))
    const { times } = index
    return {
        startLabel: index.labels[lo],
        endLabel: index.labels[hi],
        from: times ? times[lo] : null,
        // A single-label chart has no bucket width, so give its range a nonzero length to overlap anything.
        to: times ? Math.max(bucketEnd(index, hi), times[hi] + 1) : null,
    }
}

/** Maps a group range onto this chart's labels as an inclusive index range, or null when it
 *  covers none of them. On times, every bucket that overlaps `[from, to)` is in the range. */
export function matchChartGroupRange(
    index: ChartGroupXIndex,
    range: ChartGroupRange
): { startIndex: number; endIndex: number } | null {
    const { times } = index
    if (times == null || range.from == null || range.to == null) {
        const startIndex = index.byLabel.get(range.startLabel)
        const endIndex = index.byLabel.get(range.endLabel)
        if (startIndex == null || endIndex == null) {
            return null
        }
        return { startIndex: Math.min(startIndex, endIndex), endIndex: Math.max(startIndex, endIndex) }
    }
    const { from, to } = range
    // Bucket starts and ends both ascend, so binary search finds each edge.
    const startIndex = firstIndexWhere(times.length, (i) => Math.max(bucketEnd(index, i), times[i] + 1) > from)
    const endIndex = firstIndexWhere(times.length, (i) => times[i] >= to) - 1
    return startIndex <= endIndex ? { startIndex, endIndex } : null
}

/** First index in `[0, length)` where the monotonic `test` holds, or `length` when it never does. */
function firstIndexWhere(length: number, test: (i: number) => boolean): number {
    let lo = 0
    let hi = length
    while (lo < hi) {
        const mid = (lo + hi) >> 1
        if (test(mid)) {
            hi = mid
        } else {
            lo = mid + 1
        }
    }
    return lo
}
