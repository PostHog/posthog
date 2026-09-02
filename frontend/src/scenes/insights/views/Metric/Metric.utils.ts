import { dayjs } from 'lib/dayjs'
import { DATE_FORMAT_WITHOUT_YEAR, formatDate } from 'lib/utils/datetime'

// The metric summary math (total / average / latest + change pill) is shared with the Metrics product,
// so it lives in `lib/components/Metric/metricSummary`. Re-exported here to keep the insights call sites stable.
export * from 'lib/components/Metric/metricSummary'

// Sub-day bucket keys carry a time ("2026-09-02 13:00:00"), so a date-only caption renders every
// bucket in a day as the same text. Matching how the line chart and the workflows tile read their
// keys, a space in the key means the bucket needs its time.
const SUB_DAY_LABEL_FORMAT = `${DATE_FORMAT_WITHOUT_YEAR}, HH:mm`

/** Render a bucket key the app's way, without the year ("June 16" rather than "16-Jun-2026").
 *  Text that dayjs cannot parse is returned unchanged. */
export function formatMetricLabel(label: string): string {
    const parsed = dayjs(label)
    if (!parsed.isValid()) {
        return label
    }
    return formatDate(parsed, label.includes(' ') ? SUB_DAY_LABEL_FORMAT : DATE_FORMAT_WITHOUT_YEAR)
}
