import { createXAxisTickCallback, type XAxisConfig } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'

import { BIDateBucket } from '~/queries/schema/schema-business-intelligence'

function parseChartDate(label: string, timezone: string): ReturnType<typeof dayjs> {
    return /^\d{4}-\d{2}-\d{2}$/.test(label) ? dayjs.tz(label, timezone) : dayjs(label).tz(timezone)
}

export function getBIChartDateAxis(labels: string[], timezone: string, interval?: BIDateBucket): XAxisConfig {
    const formatter = createXAxisTickCallback({ allDays: labels, timezone, interval })
    const indices = new Map(labels.map((label, index) => [label, index]))
    return {
        tickFormatter: (label) => {
            const text = formatter ? formatter(label, indices.get(label) ?? 0) : label
            if (text && /^\d{4}$/.test(text)) {
                return parseChartDate(label, timezone).format(
                    interval === 'quarter' ? '[Q]Q' : interval === 'month' ? 'MMMM' : 'MMM D'
                )
            }
            return text
        },
    }
}

export function getBIChartYearGroups(
    labels: string[],
    timezone: string
): { year: number; first: string; last: string }[] {
    const groups: { year: number; first: string; last: string }[] = []
    for (const label of labels) {
        const date = parseChartDate(label, timezone)
        if (!date.isValid()) {
            continue
        }
        const year = date.year()
        const previous = groups[groups.length - 1]
        if (previous?.year === year) {
            previous.last = label
        } else {
            groups.push({ year, first: label, last: label })
        }
    }
    return groups
}
