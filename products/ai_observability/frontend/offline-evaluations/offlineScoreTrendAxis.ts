import { buildYTickFormatter } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'

export function createOfflineScoreTrendTickFormatter(
    domain: [number, number] | undefined,
    elapsed: boolean,
    timezone: string
): (value: number) => string {
    if (elapsed) {
        return buildYTickFormatter({ format: 'duration_ms' })
    }

    let format = 'MMM D, YYYY'
    if (domain) {
        const span = domain[1] - domain[0]
        const start = dayjs(domain[0]).tz(timezone)
        const end = dayjs(domain[1]).tz(timezone)
        const dateFormat = start.year() === end.year() ? 'MMM D' : 'MMM D, YYYY'
        if (span < 14 * 86400000) {
            const timeFormat = span < 10000 ? 'HH:mm:ss.SSS' : span < 3600000 ? 'HH:mm:ss' : 'HH:mm'
            format =
                start.format('YYYY-MM-DD') === end.format('YYYY-MM-DD') ? timeFormat : `${dateFormat} ${timeFormat}`
        } else {
            format = dateFormat
        }
    }
    return (value) => dayjs(value).tz(timezone).format(format)
}
