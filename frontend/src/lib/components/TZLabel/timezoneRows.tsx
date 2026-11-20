import { IconClock, IconHome, IconLaptop } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { IconLinux, IconWeb } from 'lib/lemon-ui/icons'
import { shortTimeZone } from 'lib/utils/timezones'

const OUTPUT_FORMAT = 'ddd, MMM D, YYYY h:mm A'
const OUTPUT_FORMAT_WITH_SECONDS = 'ddd, MMM D, YYYY h:mm:ss A'

export interface TimezoneRow {
    key: 'displayed' | 'device' | 'project' | 'utc' | 'unix'
    icon: JSX.Element
    label: string
    caption?: string
    value: string
    copyDescription: string
    muted: boolean
    monospace: boolean
}

interface TimezoneRowsOptions {
    showSeconds?: boolean
    displayTimezone?: string
    /** Absent before the current team loads. */
    projectTimezone?: string
}

export function getTimezoneRows(
    time: dayjs.Dayjs,
    { showSeconds, displayTimezone, projectTimezone }: TimezoneRowsOptions
): TimezoneRow[] {
    const format = showSeconds ? OUTPUT_FORMAT_WITH_SECONDS : OUTPUT_FORMAT
    const date = time.toDate()
    // A stored timezone name can be one dayjs doesn't know, and a time card must never crash the label.
    const inTimezone = (tz: string): dayjs.Dayjs => {
        try {
            return time.tz(tz)
        } catch {
            return time
        }
    }

    const rows: TimezoneRow[] = []
    if (displayTimezone) {
        rows.push({
            key: 'displayed',
            icon: <IconClock />,
            label: 'Displayed',
            caption: shortTimeZone(displayTimezone, date) ?? displayTimezone,
            value: inTimezone(displayTimezone).format(format),
            copyDescription: 'displayed timezone date',
            muted: false,
            monospace: false,
        })
    }
    rows.push({
        key: 'device',
        icon: <IconLaptop />,
        label: 'Your device',
        caption: shortTimeZone(undefined, date) ?? undefined,
        value: time.format(format),
        copyDescription: 'your device date',
        muted: displayTimezone !== undefined,
        monospace: false,
    })
    if (projectTimezone) {
        rows.push({
            key: 'project',
            icon: <IconHome />,
            label: 'Project',
            caption: shortTimeZone(projectTimezone, date) ?? undefined,
            value: inTimezone(projectTimezone).format(format),
            copyDescription: 'project timezone date',
            muted: true,
            monospace: false,
        })
    }
    if (projectTimezone !== 'UTC') {
        rows.push({
            key: 'utc',
            icon: <IconWeb />,
            label: 'UTC',
            caption: 'UTC',
            value: inTimezone('UTC').format(format),
            copyDescription: 'UTC date',
            muted: true,
            monospace: false,
        })
    }
    rows.push({
        key: 'unix',
        icon: <IconLinux />,
        label: 'UNIX',
        value: time.unix().toString(),
        copyDescription: 'UNIX timestamp',
        muted: true,
        monospace: true,
    })
    return rows
}
