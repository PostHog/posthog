import posthog from 'posthog-js'

import { Dayjs, dayjs } from 'lib/dayjs'
import { zeroPad } from 'lib/utils/numbers'

import { ActionType, DateMappingOption, EventType, IntervalType, TimeUnitType } from '~/types'

import { CUSTOM_OPTION_KEY } from './components/DateFilter/types'
import { getAppContext } from './utils/getAppContext'
import { getPrimaryPropertyForEvent } from './utils/primaryEventProperty'
import { UnexpectedNeverError } from './utils/typeChecks'

export function toParams(obj: Record<string, any>, explodeArrays: boolean = false): string {
    if (!obj) {
        return ''
    }

    function handleVal(val: any): string {
        if (dayjs.isDayjs(val)) {
            return encodeURIComponent(val.format('YYYY-MM-DD'))
        }
        val = typeof val === 'object' ? JSON.stringify(val) : val
        return encodeURIComponent(val)
    }

    return Object.entries(obj)
        .filter((item) => item[1] != undefined && item[1] != null)
        .reduce(
            (acc, [key, val]) => {
                /**
                 *  query parameter arrays can be handled in two ways
                 *  either they are encoded as a single query parameter
                 *    a=[1, 2] => a=%5B1%2C2%5D
                 *  or they are "exploded" so each item in the array is sent separately
                 *    a=[1, 2] => a=1&a=2
                 **/
                if (explodeArrays && Array.isArray(val)) {
                    val.forEach((v) => acc.push([key, v]))
                } else {
                    acc.push([key, val])
                }

                return acc
            },
            [] as [string, any][]
        )
        .map(([key, val]) => `${key}=${handleVal(val)}`)
        .join('&')
}

export function fromParamsGivenUrl(url: string): Record<string, any> {
    return !url
        ? {}
        : url
              .replace(/^\?/, '')
              .split('&')
              .reduce(
                  (paramsObject, paramString) => {
                      const [key, value] = paramString.split('=')
                      paramsObject[key] = decodeURIComponent(value)
                      return paramsObject
                  },
                  {} as Record<string, any>
              )
}

export function fromParams(): Record<string, any> {
    return fromParamsGivenUrl(window.location.search)
}

export function tryDecodeURIComponent(value: string): string {
    try {
        return decodeURIComponent(value)
    } catch {
        return value
    }
}

// Parse a tags filter value coming from URL search params.
// Supports:
// - Repeated params handled upstream and aggregated as an array
// - JSON array string (e.g. "[\"a\",\"b\"]")
// - Comma-separated string (e.g. "a,b")
export function parseTagsFilter(raw: unknown): string[] | undefined {
    if (Array.isArray(raw)) {
        return (raw as unknown[]).map((v) => String(v)).filter(Boolean)
    }
    if (typeof raw === 'string') {
        // Try JSON first
        try {
            const parsed = JSON.parse(raw)
            if (Array.isArray(parsed)) {
                return parsed.map((v) => String(v)).filter(Boolean)
            }
        } catch {
            // Fall through to comma-separated
        }
        return raw
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
    }
    return undefined
}

export const humanFriendlyMilliseconds = (timestamp: number | undefined): string | undefined => {
    if (typeof timestamp !== 'number') {
        return undefined
    }

    if (timestamp < 1000) {
        return `${Math.ceil(timestamp)}ms`
    }

    return `${(timestamp / 1000).toFixed(2)}s`
}

export function humanFriendlyDuration(
    d: string | number | null | undefined,
    {
        maxUnits,
        secondsPrecision,
        secondsFixed,
    }: { maxUnits?: number; secondsPrecision?: number; secondsFixed?: number } = {}
): string {
    // Convert `d` (seconds) to a human-readable duration string.
    // Example: `1d 10hrs 9mins 8s`
    if (d === '' || d === null || d === undefined || maxUnits === 0) {
        return ''
    }
    d = Number(d)
    if (d < 0) {
        return `-${humanFriendlyDuration(-d)}`
    }
    if (d === 0) {
        return `0s`
    }
    if (d < 1) {
        return `${Math.round(d * 1000)}ms`
    }
    if (d < 60) {
        if (secondsPrecision != null) {
            return `${parseFloat(d.toPrecision(secondsPrecision))}s` // round to s.f. then throw away trailing zeroes
        }
        return `${parseFloat(d.toFixed(secondsFixed ?? 0))}s` // round to fixed point then throw away trailing zeroes
    }

    const days = Math.floor(d / 86400)
    const h = Math.floor((d % 86400) / 3600)
    const m = Math.floor((d % 3600) / 60)
    const s = Math.floor((d % 3600) % 60)

    const dayDisplay = days > 0 ? days + 'd' : ''
    const hDisplay = h > 0 ? h + 'h' : ''
    const mDisplay = m > 0 ? m + 'm' : ''
    const sDisplay = s > 0 ? s + 's' : hDisplay || mDisplay ? '' : '0s'

    let units: string[] = []
    if (days > 0) {
        units = [dayDisplay, hDisplay].filter(Boolean)
    } else {
        units = [hDisplay, mDisplay, sDisplay].filter(Boolean)
    }
    return units.slice(0, maxUnits ?? undefined).join(' ')
}

export function humanFriendlyDiff(from: dayjs.Dayjs | string, to: dayjs.Dayjs | string): string {
    const diff = dayjs(to).diff(dayjs(from), 'seconds')
    return humanFriendlyDuration(diff)
}

export function humanFriendlyDetailedTime(
    date: dayjs.Dayjs | string | null | undefined,
    formatDate = 'MMMM DD, YYYY',
    formatTime = 'h:mm:ss A',
    options: { timestampStyle?: 'relative' | 'absolute' } = { timestampStyle: 'relative' }
): string {
    if (!date) {
        return 'Never'
    }
    const parsedDate = dayjs(date)

    if (options.timestampStyle === 'absolute') {
        return parsedDate.format(`${formatDate} ${formatTime}`)
    }

    const today = dayjs().startOf('day')
    const yesterday = today.clone().subtract(1, 'days').startOf('day')
    if (parsedDate.isSame(dayjs(), 'm')) {
        return 'Just now'
    }
    let formatString: string
    if (parsedDate.isSame(today, 'd')) {
        formatString = `[Today] ${formatTime}`
    } else if (parsedDate.isSame(yesterday, 'd')) {
        formatString = `[Yesterday] ${formatTime}`
    } else {
        formatString = `${formatDate} ${formatTime}`
    }
    return parsedDate.format(formatString)
}

export function detailedTime(date: dayjs.Dayjs | string | null | undefined): string {
    if (!date) {
        return ''
    }
    return dayjs(date).format('MMMM DD, YYYY h:mm:ss A')
}

export function colonDelimitedDuration(d: string | number | null | undefined, fixedUnits: number | null = 3): string {
    // Convert `d` (seconds) to a colon delimited duration. includes `numUnits` no. of units starting from right
    // Example: `01:10:09:08 = 1d 10hrs 9mins 8s`
    if (d === '' || d === null || d === undefined) {
        return ''
    }
    d = Number(d)

    let s = d
    let weeks = 0,
        days = 0,
        h = 0,
        m = 0

    weeks = !fixedUnits || fixedUnits > 4 ? Math.floor(s / 604800) : 0
    s -= weeks * 604800

    days = !fixedUnits || fixedUnits > 3 ? Math.floor(s / 86400) : 0
    s -= days * 86400

    h = !fixedUnits || fixedUnits > 2 ? Math.floor(s / 3600) : 0
    s -= h * 3600

    m = !fixedUnits || fixedUnits > 1 ? Math.floor(s / 60) : 0
    s -= m * 60

    s = Math.floor(s)

    let stopTrimming = false
    const units: string[] = []

    ;[weeks, days, h, m, s].forEach((unit, i) => {
        if (!fixedUnits && !unit && !stopTrimming && i < 3) {
            return
        }
        units.push(zeroPad(unit, 2))
        stopTrimming = true
    })

    if (fixedUnits) {
        return units.slice(-fixedUnits).join(':')
    }

    return units.join(':')
}

export function reverseColonDelimitedDuration(duration?: string | null): number | null {
    if (!duration) {
        return null
    }

    if (!/^(\d\d?:)*(\d\d?)$/.test(duration)) {
        return null
    }

    let seconds = 0
    const units = duration
        .split(':')
        .map((unit) => Number(unit))
        .reverse()

    ;[1, 60, 3600, 86400, 604800].forEach((unit, index) => {
        if (units[index]) {
            seconds += units[index] * unit
        }
    })

    return seconds
}

export function stripHTTP(url: string): string {
    url = url.replace(/(^[0-9]+_)/, '')
    url = url.replace(/(^\w+:|^)\/\//, '')
    return url
}

export function isDomain(url: string | URL): boolean {
    try {
        const parsedUrl = typeof url === 'string' ? new URL(url) : url
        if (parsedUrl.protocol.includes('http') && (!parsedUrl.pathname || parsedUrl.pathname === '/')) {
            return true
        }
        if (!parsedUrl.pathname.replace(/^\/\//, '').includes('/')) {
            return true
        }
    } catch {
        return false
    }
    return false
}

export function isURL(input: any): boolean {
    if (!input || typeof input !== 'string') {
        return false
    }
    const regexp = /^(http|capacitor|https):\/\/[\w*.-]+[\w*.-]+[\w\-._~:/?#[\]@%!$&'()*+,;=]+$/
    return !!input.trim().match(regexp)
}

export function isExternalLink(input: any): boolean {
    if (!input || typeof input !== 'string') {
        return false
    }
    const regexp = /^(https?:|mailto:|\/api\/)/
    return !!input.trim().match(regexp)
}

export function isEmail(string: string, options?: { requireTLD?: boolean }): boolean {
    if (!string) {
        return false
    }
    // https://html.spec.whatwg.org/multipage/input.html#valid-e-mail-address
    const regexp = options?.requireTLD
        ? /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$/
        : /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/
    return !!string.match?.(regexp)
}

export function eventToDescription(
    event: Pick<EventType, 'elements' | 'event' | 'properties'>,
    shortForm: boolean = false
): string {
    if (event.event === '$autocapture') {
        return autoCaptureEventToDescription(event, shortForm)
    }
    // For events with a taxonomy-default primary property (e.g. `$pageview` -> `$pathname`,
    // `$screen` -> `$screen_name`, `$feature_flag_called` -> `$feature_flag`), use the property's
    // value as the description so consumers (notebooks, save-as-action, funnel labels, ...) get
    // useful context instead of the bare event name. Returns the event name when the property
    // isn't present on the event so callers always get something to display.
    const primaryKey = getPrimaryPropertyForEvent(event.event)
    if (primaryKey) {
        const value = event.properties[primaryKey]
        if (value != null && value !== '') {
            return String(value)
        }
    }
    return event.event
}

// $event_type to verb map
export const eventTypeToVerb: { [key: string]: string } = {
    click: 'clicked',
    change: 'changed',
    submit: 'submitted',
    touch: 'touched a',
    value_changed: 'changed value in',
    toggle: 'toggled',
    menu_action: 'pressed menu',
    swipe: 'swiped',
    pinch: 'pinched',
    pan: 'panned',
    rotation: 'rotated',
    long_press: 'long pressed',
    scroll: 'scrolled in',
}

export function autoCaptureEventToDescription(
    event: Pick<EventType, 'elements' | 'event' | 'properties'>,
    shortForm: boolean = false
): string {
    if (event.event !== '$autocapture') {
        return event.event
    }

    const getVerb = (): string => eventTypeToVerb[event.properties.$event_type] || 'interacted with'

    const getTag = (): string => {
        if (event.elements?.[0]?.tag_name === 'a') {
            return 'link'
        } else if (event.elements?.[0]?.tag_name === 'img') {
            return 'image'
        }
        return event.elements?.[0]?.tag_name ?? 'element'
    }

    const getValue = (): string | null => {
        if (event.properties.$el_text) {
            return `${shortForm ? '' : 'with text '}"${event.properties.$el_text}"`
        } else if (event.elements?.[0]?.text) {
            return `${shortForm ? '' : 'with text '}"${event.elements[0].text}"`
        } else if (event.elements?.[0]?.attributes?.['attr__aria-label']) {
            return `${shortForm ? '' : 'with aria label '}"${event.elements[0].attributes['attr__aria-label']}"`
        }
        return null
    }

    if (shortForm) {
        return [getVerb(), getValue() ?? getTag()].filter((x) => x).join(' ')
    }
    const value = getValue()
    return [getVerb(), getTag(), value].filter((x) => x).join(' ')
}

export function determineDifferenceType(
    firstDate: dayjs.Dayjs | string,
    secondDate: dayjs.Dayjs | string
): 'year' | 'month' | 'week' | 'day' | 'hour' | 'minute' | 'second' {
    const first = dayjs(firstDate)
    const second = dayjs(secondDate)
    if (first.diff(second, 'years') !== 0) {
        return 'year'
    } else if (first.diff(second, 'months') !== 0) {
        return 'month'
    } else if (first.diff(second, 'weeks') !== 0) {
        return 'week'
    } else if (first.diff(second, 'days') !== 0) {
        return 'day'
    } else if (first.diff(second, 'hours') !== 0) {
        return 'hour'
    }
    return 'minute'
}

export const DATE_FORMAT = 'MMMM D, YYYY'
export const DATE_TIME_FORMAT = 'MMMM D, YYYY HH:mm:ss'
export const DATE_FORMAT_WITHOUT_YEAR = 'MMMM D'
export const DATE_FORMAT_WITHOUT_DAY = 'HH:mm:ss'

export const formatDate = (date: dayjs.Dayjs, format?: string): string => {
    return date.format(format ?? DATE_FORMAT)
}

export const formatDateTime = (date: dayjs.Dayjs, format?: string): string => {
    return date.format(format ?? DATE_TIME_FORMAT)
}

export const formatDateRange = (dateFrom: dayjs.Dayjs, dateTo: dayjs.Dayjs, format?: string): string => {
    let formatFrom = format ?? DATE_FORMAT
    const formatTo = format ?? DATE_FORMAT
    if ((!format || format === DATE_FORMAT) && dateFrom.year() === dateTo.year()) {
        formatFrom = DATE_FORMAT_WITHOUT_YEAR
    }
    return `${dateFrom.format(formatFrom)} - ${dateTo.format(formatTo)}`
}

export const formatDateTimeRange = (dateFrom: dayjs.Dayjs, dateTo: dayjs.Dayjs): string => {
    const MONTHDAY = 'MMMM D'
    const COMMA = ', '
    const YEAR = 'YYYY '
    const TIME = 'HH:mm'
    const SECONDS = ':ss'

    let fromComponents = [MONTHDAY, COMMA, YEAR, TIME, SECONDS]
    let toComponents = [MONTHDAY, COMMA, YEAR, TIME, SECONDS]
    if (dateFrom.year() === dateTo.year()) {
        toComponents = toComponents.filter((x) => x !== YEAR)
        if (dateTo.year() === dayjs().year()) {
            fromComponents = fromComponents.filter((x) => x !== YEAR)
        }

        if (dateFrom.isSame(dateTo, 'day')) {
            toComponents = toComponents.filter((x) => x !== MONTHDAY)
            toComponents = toComponents.filter((x) => x !== COMMA)
            if (dateFrom.isSame(dayjs(), 'day')) {
                fromComponents = fromComponents.filter((x) => x !== MONTHDAY)
                fromComponents = fromComponents.filter((x) => x !== COMMA)
            }
        }

        if (dateFrom.isSame(dayjs(dateFrom).startOf('day')) && dateTo.isSame(dayjs(dateTo).startOf('day'))) {
            fromComponents = fromComponents.filter((x) => x !== TIME)
            toComponents = toComponents.filter((x) => x !== TIME)
        }

        if (dateFrom.second() === 0 && dateTo.second() === 0) {
            fromComponents = fromComponents.filter((x) => x !== SECONDS)
            toComponents = toComponents.filter((x) => x !== SECONDS)
        }

        if (!fromComponents.includes(YEAR) && !fromComponents.includes(TIME)) {
            fromComponents = fromComponents.filter((x) => x !== COMMA)
        }

        if (!toComponents.includes(YEAR) && !toComponents.includes(TIME)) {
            toComponents = toComponents.filter((x) => x !== COMMA)
        }
    }
    return `${dateFrom.format(fromComponents.join(''))} - ${dateTo.format(toComponents.join(''))}`
}

/** Returns the start of the current week, respecting the team's week start day (0=Sunday, 1=Monday). */
function startOfWeek(date: dayjs.Dayjs, weekStartDay?: number | null): dayjs.Dayjs {
    const start = weekStartDay === 1 ? 1 : 0
    return date.subtract((date.day() - start + 7) % 7, 'day').startOf('day')
}

export const dateMapping: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    {
        key: 'Today',
        values: ['dStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.startOf('d').format(DATE_FORMAT),
        defaultInterval: 'hour',
    },
    {
        key: 'Yesterday',
        values: ['-1dStart', '-1dEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.subtract(1, 'd').format(DATE_FORMAT),
        defaultInterval: 'hour',
    },
    {
        key: 'Last hour',
        values: ['-1h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(1, 'h'), date),
        defaultInterval: 'minute',
    },
    {
        key: 'Last 24 hours',
        values: ['-24h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(24, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 48 hours',
        values: ['-48h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(48, 'h'), date.endOf('d')),
        inactive: true,
        defaultInterval: 'hour',
    },
    {
        key: 'Last 7 days',
        values: ['-7d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(7, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Last 14 days',
        values: ['-14d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(14, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Last 30 days',
        values: ['-30d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(30, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Last 90 days',
        values: ['-90d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(90, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Last 180 days',
        values: ['-180d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(180, 'd'), date.endOf('d')),
        defaultInterval: 'month',
    },

    {
        key: 'Last week',
        values: ['-1wStart', '-1wEnd'],
        getFormattedDate: (date: dayjs.Dayjs, _format?: string, weekStartDay?: number): string => {
            const lastWeekStart = startOfWeek(date, weekStartDay).subtract(7, 'day')
            return formatDateRange(lastWeekStart, lastWeekStart.add(6, 'day').endOf('d'))
        },
        defaultInterval: 'day',
    },
    {
        key: 'Last month',
        values: ['-1mStart', '-1mEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string =>
            formatDateRange(date.subtract(1, 'month').startOf('month'), date.subtract(1, 'month').endOf('month')),
        defaultInterval: 'day',
    },
    {
        key: 'This week',
        values: ['wStart'],
        getFormattedDate: (date: dayjs.Dayjs, _format?: string, weekStartDay?: number): string =>
            formatDateRange(startOfWeek(date, weekStartDay), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'This month',
        values: ['mStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('month'), date.endOf('month')),
        defaultInterval: 'day',
    },
    {
        key: 'Year to date',
        values: ['yStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('y'), date.endOf('d')),
        defaultInterval: 'month',
    },
    {
        key: 'All time',
        values: ['all'],
        defaultInterval: 'month',
    },
]

export const isDate = /([0-9]{4}-[0-9]{2}-[0-9]{2})/

export function getFormattedLastWeekDate(lastDay: dayjs.Dayjs = dayjs()): string {
    return formatDateRange(lastDay.subtract(7, 'week'), lastDay.endOf('d'))
}

const dateOptionsMap = {
    y: 'year',
    q: 'quarter',
    m: 'month',
    w: 'week',
    d: 'day',
    h: 'hour',
    M: 'minute',
    s: 'second',
} as const

export function dateFilterToText(
    dateFrom: string | dayjs.Dayjs | null | undefined,
    dateTo: string | dayjs.Dayjs | null | undefined,
    defaultValue: string | null,
    dateOptions: DateMappingOption[] = dateMapping,
    isDateFormatted: boolean = false,
    dateFormat: string = DATE_FORMAT,
    startOfRange: boolean = false,
    weekStartDay?: number
): string | null {
    if (dayjs.isDayjs(dateFrom) && dayjs.isDayjs(dateTo)) {
        return formatDateRange(dateFrom, dateTo, dateFormat)
    }
    dateFrom = (dateFrom || undefined) as string | undefined
    dateTo = (dateTo || undefined) as string | undefined

    if (isDate.test(dateFrom || '') && isDate.test(dateTo || '')) {
        if (isDateFormatted) {
            return formatDateRange(dayjs(dateFrom, 'YYYY-MM-DD'), dayjs(dateTo, 'YYYY-MM-DD'))
        }
        if (dateFrom?.includes('T') || dateTo?.includes('T')) {
            // Parse each date individually - ISO 8601 datetimes (with T) use native parsing
            // to correctly handle seconds/milliseconds, plain dates use 'YYYY-MM-DD'
            const parsedFrom = dateFrom?.includes('T') ? dayjs(dateFrom) : dayjs(dateFrom, 'YYYY-MM-DD')
            const parsedTo = dateTo?.includes('T') ? dayjs(dateTo) : dayjs(dateTo, 'YYYY-MM-DD')
            return formatDateTimeRange(parsedFrom, parsedTo)
        }
        return `${dateFrom} - ${dateTo}`
    }

    // From date to today
    if (isDate.test(dateFrom || '') && !isDate.test(dateTo || '')) {
        const days = dayjs().diff(dayjs(dateFrom), 'days')
        if (days > 366) {
            return isDateFormatted ? `${dateFrom} - today` : formatDateRange(dayjs(dateFrom), dayjs())
        } else if (days > 0) {
            return isDateFormatted ? formatDateRange(dayjs(dateFrom), dayjs()) : `Last ${days} days`
        } else if (days === 0) {
            return isDateFormatted ? dayjs(dateFrom).format(dateFormat) : `Today`
        }
        return isDateFormatted ? `${dayjs(dateFrom).format(dateFormat)} - ` : `Starting from ${dateFrom}`
    }

    for (const { key, values, getFormattedDate } of dateOptions) {
        if (values[0] === dateFrom && values[1] === dateTo && key !== CUSTOM_OPTION_KEY) {
            return isDateFormatted && getFormattedDate ? getFormattedDate(dayjs(), dateFormat, weekStartDay) : key
        }
    }

    if (dateFrom) {
        const dateOption = dateOptionsMap[dateFrom.slice(-1) as keyof typeof dateOptionsMap]
        const counter = parseInt(dateFrom.slice(1, -1))
        if (dateOption && counter) {
            let date = null
            switch (dateOption) {
                case 'year':
                    date = dayjs().subtract(counter, 'y')
                    break
                case 'hour':
                    date = dayjs().subtract(counter, 'h')
                    break
                case 'quarter':
                    date = dayjs().subtract(counter * 3, 'M')
                    break
                case 'month':
                    date = dayjs().subtract(counter, 'M')
                    break
                case 'week':
                    date = dayjs().subtract(counter * 7, 'd')
                    break
                case 'minute':
                    date = dayjs().subtract(counter, 'm')
                    break
                case 'second':
                    date = dayjs().subtract(counter, 's')
                    break
                default:
                    date = dayjs().subtract(counter, 'd')
                    break
            }
            if (isDateFormatted) {
                return formatDateRange(date, dayjs().endOf('d'))
            } else if (startOfRange) {
                return formatDate(date, dateFormat)
            }
            return `Last ${counter} ${dateOption}${counter > 1 ? 's' : ''}`
        }
    }

    return defaultValue
}

// Converts a dateFrom string ("-2w") into english: "2 weeks"
export function dateFromToText(dateFrom: string): string | undefined {
    const dateOption: (typeof dateOptionsMap)[keyof typeof dateOptionsMap] =
        dateOptionsMap[dateFrom.slice(-1) as keyof typeof dateOptionsMap]
    const counter = parseInt(dateFrom.slice(1, -1))
    if (dateOption && counter) {
        return `${counter} ${dateOption}${counter > 1 ? 's' : ''}`
    }
    return undefined
}

export type DateComponents = {
    amount: number
    unit: (typeof dateOptionsMap)[keyof typeof dateOptionsMap]
    clip: 'Start' | 'End'
}

export const isStringDateRegex = /^([-+]?)([0-9]*)([hdwmqy])(|Start|End)$/
export function dateStringToComponents(date: string | null): DateComponents | null {
    if (!date) {
        return null
    }
    const matches = date.match(isStringDateRegex)
    if (!matches) {
        return null
    }
    const [, sign, rawAmount, rawUnit, clip] = matches
    const amount = rawAmount ? parseInt(sign + rawAmount) : 0
    const unit = dateOptionsMap[rawUnit as keyof typeof dateOptionsMap] || 'day'
    return { amount, unit, clip: clip as 'Start' | 'End' }
}

export function componentsToDayJs(
    { amount, unit, clip }: DateComponents,
    offset?: Dayjs,
    timezone: string = 'UTC'
): Dayjs {
    const dayjsInstance = offset ?? dayjs().tz(timezone)
    let response: dayjs.Dayjs
    switch (unit) {
        case 'year':
            response = dayjsInstance.add(amount, 'year')
            break
        case 'quarter':
            response = dayjsInstance.add(amount * 3, 'month')
            break
        case 'month':
            response = dayjsInstance.add(amount, 'month')
            break
        case 'week':
            response = dayjsInstance.add(amount * 7, 'day')
            break
        case 'day':
            response = dayjsInstance.add(amount, 'day')
            break
        case 'hour':
            response = dayjsInstance.add(amount, 'hour')
            break
        case 'minute':
            response = dayjsInstance.add(amount, 'minute')
            break
        case 'second':
            response = dayjsInstance.add(amount, 'second')
            break
        default:
            throw new UnexpectedNeverError(unit)
    }

    if (clip === 'Start') {
        return response.startOf(unit)
    } else if (clip === 'End') {
        return response.endOf(unit)
    }
    return response
}

/** Convert a string like "-30d" or "2022-02-02" or "-1mEnd" to `Dayjs().startOf('day')` */
export function dateStringToDayJs(date: string | null, timezone: string = 'UTC'): dayjs.Dayjs | null {
    if (isDate.test(date || '')) {
        return dayjs.tz(date, timezone)
    }
    const dateComponents = dateStringToComponents(date)
    if (!dateComponents) {
        return null
    }
    const offset: dayjs.Dayjs = dayjs().tz(timezone).startOf('day')
    const response = componentsToDayJs(dateComponents, offset, timezone)
    return response
}

export function isValidRelativeOrAbsoluteDate(date: string): boolean {
    if (isStringDateRegex.test(date)) {
        return true
    }
    if (dayjs(date).isValid()) {
        return true
    }
    if (date === 'all') {
        return true
    }
    return false
}

export const getDefaultInterval = (dateFrom: string | null, dateTo: string | null): IntervalType => {
    // use the default mapping if we can
    for (const mapping of dateMapping) {
        const mappingFrom = mapping.values[0] ?? null
        const mappingTo = mapping.values[1] ?? null
        if (mappingFrom === dateFrom && mappingTo === dateTo && mapping.defaultInterval) {
            return mapping.defaultInterval
        }
    }

    const parsedDateFrom = dateStringToComponents(dateFrom)
    const parsedDateTo = dateStringToComponents(dateTo)

    if (parsedDateFrom?.unit === 'hour' || parsedDateTo?.unit === 'hour') {
        return 'hour'
    }

    if (
        parsedDateFrom?.unit === 'day' ||
        parsedDateTo?.unit === 'day' ||
        dateFrom === 'mStart' ||
        dateFrom === 'wStart'
    ) {
        return 'day'
    }

    if (
        (parsedDateFrom?.unit === 'month' && parsedDateFrom.amount <= 3) ||
        (parsedDateTo?.unit === 'month' && parsedDateTo.amount <= 3) ||
        (parsedDateFrom?.unit === 'quarter' && parsedDateFrom.amount <= 1) ||
        (parsedDateTo?.unit === 'quarter' && parsedDateTo.amount <= 1)
    ) {
        return 'day'
    }

    if (
        parsedDateFrom?.unit === 'month' ||
        parsedDateTo?.unit === 'month' ||
        parsedDateFrom?.unit === 'quarter' ||
        parsedDateTo?.unit === 'quarter' ||
        parsedDateFrom?.unit === 'year' ||
        parsedDateTo?.unit === 'year' ||
        dateFrom === 'all'
    ) {
        return 'month'
    }

    const dateFromDayJs = dateStringToDayJs(dateFrom)
    const dateToDayJs = dateStringToDayJs(dateTo)

    const intervalMonths = dateFromDayJs?.diff(dateToDayJs, 'month')
    if (intervalMonths != null && Math.abs(intervalMonths) >= 2) {
        return 'month'
    }
    const intervalDays = dateFromDayJs?.diff(dateToDayJs, 'day')
    if (intervalDays != null && Math.abs(intervalDays) >= 14) {
        return 'week'
    }
    if (intervalDays != null && Math.abs(intervalDays) >= 2) {
        return 'day'
    }
    const intervalHours = dateFromDayJs?.diff(dateToDayJs, 'hour')
    if (intervalHours != null && Math.abs(intervalHours) >= 1) {
        return 'hour'
    }

    return 'day'
}

/* If the interval changes, check if it's compatible with the selected dates, and return new dates
 * from a map of sensible defaults if not */
export const areDatesValidForInterval = (
    interval: IntervalType,
    oldDateFrom: string | null,
    oldDateTo: string | null
): boolean => {
    const parsedOldDateFrom = dateStringToDayJs(oldDateFrom)
    const parsedOldDateTo = dateStringToDayJs(oldDateTo) || dayjs()

    if (oldDateFrom === 'all' || !parsedOldDateFrom) {
        return interval === 'month'
    } else if (interval === 'month') {
        return parsedOldDateTo.diff(parsedOldDateFrom, 'month') >= 2
    } else if (interval === 'week') {
        return parsedOldDateTo.diff(parsedOldDateFrom, 'week') >= 2
    } else if (interval === 'day') {
        const diff = parsedOldDateTo.diff(parsedOldDateFrom, 'day')
        return diff >= 2
    } else if (interval === 'hour') {
        return (
            parsedOldDateTo.diff(parsedOldDateFrom, 'hour') >= 2 &&
            parsedOldDateTo.diff(parsedOldDateFrom, 'hour') < 24 * 7 * 2 // 2 weeks
        )
    } else if (interval === 'minute') {
        return (
            parsedOldDateTo.diff(parsedOldDateFrom, 'minute') >= 2 &&
            parsedOldDateTo.diff(parsedOldDateFrom, 'minute') < 60 * 12 // 12 hours. picked based on max graph resolution
        )
    } else if (interval === 'second') {
        return (
            parsedOldDateTo.diff(parsedOldDateFrom, 'second') >= 2 &&
            parsedOldDateTo.diff(parsedOldDateFrom, 'second') < 60 * 60 // 1 hour
        )
    }
    throw new UnexpectedNeverError(interval)
}

const defaultDatesForInterval = {
    second: { dateFrom: '-1M', dateTo: null },
    minute: { dateFrom: '-1h', dateTo: null },
    hour: { dateFrom: '-24h', dateTo: null },
    day: { dateFrom: '-7d', dateTo: null },
    week: { dateFrom: '-28d', dateTo: null },
    month: { dateFrom: '-6m', dateTo: null },
}

export const updateDatesWithInterval = (
    interval: IntervalType,
    oldDateFrom: string | null,
    oldDateTo: string | null
): { dateFrom: string | null; dateTo: string | null } => {
    if (areDatesValidForInterval(interval, oldDateFrom, oldDateTo)) {
        return {
            dateFrom: oldDateFrom,
            dateTo: oldDateTo,
        }
    }
    return defaultDatesForInterval[interval]
}

export function is12HoursOrLess(dateFrom: string | undefined | null): boolean {
    if (!dateFrom) {
        return false
    }
    return dateFrom.search(/^-([0-9]|1[0-2])h$/) != -1
}
export function isLessThan2Days(dateFrom: string | undefined | null): boolean {
    if (!dateFrom) {
        return false
    }
    return dateFrom.search(/^-(4[0-7]|[0-3]?[0-9])h|[1-2]d$/) != -1
}

export function parseGithubRepoURL(url: string): Record<string, string> {
    const match = url.match(
        /^https?:\/\/(?:www\.)?github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)(\/(commit|tree|releases\/tag)\/([A-Za-z0-9_.\-/]+))?/
    )

    if (!match) {
        throw new Error(`${url} is not a valid GitHub URL`)
    }

    const [, user, repo, , type, path] = match
    return { user, repo, type, path }
}

/**
 * Return the short timezone identifier for a specific timezone (e.g. BST, EST, PDT, UTC+2).
 * @param timeZone E.g. 'America/New_York'
 * @param atDate
 */
export function shortTimeZone(timeZone?: string, atDate?: Date): string | null {
    const date = atDate ? new Date(atDate) : new Date()
    try {
        const localeTimeStringParts = date
            .toLocaleTimeString('en-us', { timeZoneName: 'short', timeZone: timeZone || undefined })
            .replace('GMT', 'UTC')
            .split(' ')
        return localeTimeStringParts[localeTimeStringParts.length - 1]
    } catch (e) {
        posthog.captureException(e)
        return null
    }
}

export function timeZoneLabel(timeZone: string, offset: number): string {
    const formattedZone = timeZone.replace(/\//g, ' / ').replace(/_/g, ' ')
    const sign = offset === 0 ? '±' : offset > 0 ? '+' : '-'
    const hours = Math.floor(Math.abs(offset))
    const minutes = Math.round((Math.abs(offset) % 1) * 60)
        .toString()
        .padStart(2, '0')

    return `${formattedZone} (UTC${sign}${hours}:${minutes})`
}

export function humanTzOffset(timezone?: string): string {
    const offset = dayjs().tz(timezone).utcOffset() / 60
    if (!offset) {
        return 'no offset'
    }
    const absoluteOffset = Math.abs(offset)
    const hourForm = absoluteOffset === 1 ? 'hour' : 'hours'
    const direction = offset > 0 ? 'ahead' : 'behind'
    return `${absoluteOffset} ${hourForm} ${direction}`
}

export function floorMsToClosestSecond(ms: number): number {
    return Math.floor(ms / 1000) * 1000
}

export function ceilMsToClosestSecond(ms: number): number {
    return Math.ceil(ms / 1000) * 1000
}

export function getEventNamesForAction(actionId: string | number, allActions: ActionType[]): string[] {
    const id = parseInt(String(actionId))
    return allActions
        .filter((a) => a.id === id)
        .flatMap((a) => a.steps?.filter((step) => step.event).map((step) => String(step.event)) as string[])
}

export const isUserLoggedIn = (): boolean => !getAppContext()?.anonymous

export function calculateDays(timeValue: number, timeUnit: TimeUnitType): number {
    if (timeUnit === TimeUnitType.Year) {
        return timeValue * 365
    }
    if (timeUnit === TimeUnitType.Month) {
        return timeValue * 30
    }
    if (timeUnit === TimeUnitType.Week) {
        return timeValue * 7
    }
    return timeValue
}

// Compute the ISO week string for a given date
// Useful above to show the toast once per week
export function getISOWeekString(date = new Date()): string {
    const dayjs_date = dayjs(date)

    const year = dayjs_date.year()
    const week = dayjs_date.week()

    return `${year}-W${week}`
}

export function getRelativeNextPath(nextPath: string | null | undefined, location: Location): string | null {
    if (!nextPath || typeof nextPath !== 'string') {
        return null
    }
    let decoded: string
    try {
        decoded = decodeURIComponent(nextPath)
    } catch {
        decoded = nextPath
    }

    // Protocol-relative URLs (e.g., //evil.com/test) are not allowed
    if (decoded.startsWith('//')) {
        return null
    }

    // Root-relative path — resolve against the current origin and verify it doesn't escape.
    // Browsers normalize backslashes in special-scheme URLs per WHATWG, so a raw startsWith('/')
    // check would accept '/\\evil.com/path', which the browser then loads as '//evil.com/path'.
    if (decoded.startsWith('/')) {
        try {
            const url = new URL(decoded, location.origin)
            if (url.origin !== location.origin) {
                return null
            }
            return url.pathname + url.search + url.hash
        } catch {
            return null
        }
    }

    // Try to parse as a full URL
    try {
        const url = new URL(decoded)
        if ((url.protocol === 'http:' || url.protocol === 'https:') && url.origin === location.origin) {
            return url.pathname + url.search + url.hash
        }
        return null
    } catch {
        return null
    }
}
