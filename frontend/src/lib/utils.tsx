import equal from 'fast-deep-equal'
import { tagColors } from 'lib/colors'
import { WEBHOOK_SERVICES } from 'lib/constants'
import { Dayjs, dayjs } from 'lib/dayjs'
import posthog from 'posthog-js'
import { CSSProperties } from 'react'

import {
    ActionType,
    ActorType,
    DateMappingOption,
    EventType,
    GroupActorType,
    IntervalType,
    PropertyOperator,
    PropertyType,
    TimeUnitType,
} from '~/types'

import { CUSTOM_OPTION_KEY } from './components/DateFilter/types'
import { LemonTagType } from './lemon-ui/LemonTag'
import { getAppContext } from './utils/getAppContext'

// WARNING: Be very careful importing things here. This file is heavily used and can trigger a lot of cyclic imports
// Preferably create a dedicated file in utils/..

export function uuid(): string {
    return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, (c) =>
        (
            parseInt(c) ^
            ((typeof window?.crypto !== 'undefined' // in node tests, jsdom doesn't implement window.crypto
                ? window.crypto.getRandomValues(new Uint8Array(1))[0]
                : Math.floor(Math.random() * 256)) &
                (15 >> (parseInt(c) / 4)))
        ).toString(16)
    )
}

export function areObjectValuesEmpty(obj?: Record<string, any>): boolean {
    return (
        !!obj && typeof obj === 'object' && !Object.values(obj).some((x) => x !== null && x !== '' && x !== undefined)
    )
}

// taken from https://stackoverflow.com/questions/10420352/converting-file-size-in-bytes-to-human-readable-string/10420404
export const humanizeBytes = (fileSizeInBytes: number | null): string => {
    if (fileSizeInBytes === null) {
        return ''
    }

    let i = -1
    let convertedBytes = fileSizeInBytes
    const byteUnits = ['kB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB']
    do {
        convertedBytes = convertedBytes / 1024
        i++
    } while (convertedBytes > 1024)

    if (convertedBytes < 0.1) {
        return fileSizeInBytes + ' bytes'
    }
    return convertedBytes.toFixed(2) + ' ' + byteUnits[i]
}

export function toSentenceCase(str: string): string {
    return str.replace(/\b\w/g, (c) => c.toUpperCase())
}

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
        .reduce((acc, [key, val]) => {
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
        }, [] as [string, any][])
        .map(([key, val]) => `${key}=${handleVal(val)}`)
        .join('&')
}

export function fromParamsGivenUrl(url: string): Record<string, any> {
    return !url
        ? {}
        : url
              .replace(/^\?/, '')
              .split('&')
              .reduce((paramsObject, paramString) => {
                  const [key, value] = paramString.split('=')
                  paramsObject[key] = decodeURIComponent(value)
                  return paramsObject
              }, {} as Record<string, any>)
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

/** Return percentage from number, e.g. 0.234 is 23.4%. */
export function percentage(
    division: number,
    maximumFractionDigits: number = 2,
    fixedPrecision: boolean = false
): string {
    if (division === Infinity) {
        return '∞%'
    }

    return division.toLocaleString('en-US', {
        style: 'percent',
        maximumFractionDigits,
        minimumFractionDigits: fixedPrecision ? maximumFractionDigits : undefined,
    })
}

export const selectStyle: Record<string, (base: Partial<CSSProperties>) => Partial<CSSProperties>> = {
    control: (base) => ({
        ...base,
        height: 31,
        minHeight: 31,
    }),
    indicatorsContainer: (base) => ({
        ...base,
        height: 31,
    }),
    input: (base) => ({
        ...base,
        paddingBottom: 0,
        paddingTop: 0,
        margin: 0,
        opacity: 1,
    }),
    valueContainer: (base) => ({
        ...base,
        padding: '0 8px',
        marginTop: -2,
    }),
    option: (base) => ({
        ...base,
        padding: '2px 15px',
    }),
}

export function splitKebabCase(string: string): string {
    return string.replace(/-/g, ' ')
}

export function capitalizeFirstLetter(string: string): string {
    return string.charAt(0).toUpperCase() + string.slice(1)
}

export function lowercaseFirstLetter(string: string): string {
    return string.charAt(0).toLowerCase() + string.slice(1)
}

export function fullName(props: { first_name?: string; last_name?: string }): string {
    return `${props.first_name || ''} ${props.last_name || ''}`.trim()
}

export const genericOperatorMap: Record<string, string> = {
    exact: '= equals',
    is_not: "≠ doesn't equal",
    icontains: '∋ contains',
    not_icontains: "∌ doesn't contain",
    regex: '∼ matches regex',
    not_regex: "≁ doesn't match regex",
    gt: '> greater than',
    lt: '< less than',
    is_set: '✓ is set',
    is_not_set: '✕ is not set',
}

export const stringOperatorMap: Record<string, string> = {
    exact: '= equals',
    is_not: "≠ doesn't equal",
    icontains: '∋ contains',
    not_icontains: "∌ doesn't contain",
    regex: '∼ matches regex',
    not_regex: "≁ doesn't match regex",
    is_set: '✓ is set',
    is_not_set: '✕ is not set',
}

export const stringArrayOperatorMap: Record<string, string> = {
    exact: '= equals',
    is_not: "≠ doesn't equal",
    icontains: '∋ contains',
    not_icontains: "∌ doesn't contain",
    regex: '∼ matches regex',
    not_regex: "≁ doesn't match regex",
}

export const numericOperatorMap: Record<string, string> = {
    exact: '= equals',
    is_not: "≠ doesn't equal",
    regex: '∼ matches regex',
    not_regex: "≁ doesn't match regex",
    gt: '> greater than',
    lt: '< less than',
    is_set: '✓ is set',
    is_not_set: '✕ is not set',
}

export const dateTimeOperatorMap: Record<string, string> = {
    is_date_exact: '= equals',
    is_date_before: '< before',
    is_date_after: '> after',
    is_set: '✓ is set',
    is_not_set: '✕ is not set',
}

export const booleanOperatorMap: Record<string, string> = {
    exact: '= equals',
    is_not: "≠ doesn't equal",
    is_set: '✓ is set',
    is_not_set: '✕ is not set',
}

export const durationOperatorMap: Record<string, string> = {
    gt: '> greater than',
    lt: '< less than',
}

export const selectorOperatorMap: Record<string, string> = {
    exact: '= equals',
    is_not: "≠ doesn't equal",
}

export const cohortOperatorMap: Record<string, string> = {
    in: 'user in',
    not_in: 'user not in',
}

export const stickinessOperatorMap: Record<string, string> = {
    exact: '= Exactly',
    gte: '≥ At least',
    lte: '≤ At most (but at least once)',
}

export const cleanedPathOperatorMap: Record<string, string> = {
    is_cleaned_path_exact: '= equals',
}

export const assigneeOperatorMap: Record<string, string> = {
    exact: '= is',
    is_not: '≠ is not',
    is_not_set: '✕ is not set',
}

export const allOperatorsMapping: Record<string, string> = {
    ...assigneeOperatorMap,
    ...stickinessOperatorMap,
    ...dateTimeOperatorMap,
    ...stringOperatorMap,
    ...stringArrayOperatorMap,
    ...numericOperatorMap,
    ...genericOperatorMap,
    ...booleanOperatorMap,
    ...durationOperatorMap,
    ...selectorOperatorMap,
    ...cohortOperatorMap,
    ...cleanedPathOperatorMap,
    // slight overkill to spread all of these into the map
    // but gives freedom for them to diverge more over time
}

const operatorMappingChoice: Record<keyof typeof PropertyType, Record<string, string>> = {
    DateTime: dateTimeOperatorMap,
    String: stringOperatorMap,
    Numeric: numericOperatorMap,
    Boolean: booleanOperatorMap,
    Duration: durationOperatorMap,
    Selector: selectorOperatorMap,
    Cohort: cohortOperatorMap,
    Assignee: assigneeOperatorMap,
    StringArray: stringArrayOperatorMap,
}

export function chooseOperatorMap(propertyType: PropertyType | undefined): Record<string, string> {
    let choice = genericOperatorMap
    if (propertyType) {
        choice = operatorMappingChoice[propertyType] || genericOperatorMap
    }
    return choice
}

export function isOperatorMulti(operator: PropertyOperator): boolean {
    return [PropertyOperator.Exact, PropertyOperator.IsNot].includes(operator)
}

export function isOperatorFlag(operator: PropertyOperator): boolean {
    // these filter operators can only be just set, no additional parameter
    return [PropertyOperator.IsSet, PropertyOperator.IsNotSet, PropertyOperator.In, PropertyOperator.NotIn].includes(
        operator
    )
}

export function isOperatorCohort(operator: PropertyOperator): boolean {
    // these filter operators use value different ( to represent the number of the cohort )
    return [PropertyOperator.In, PropertyOperator.NotIn].includes(operator)
}

export function isOperatorRegex(operator: PropertyOperator): boolean {
    return [PropertyOperator.Regex, PropertyOperator.NotRegex].includes(operator)
}

export function isOperatorRange(operator: PropertyOperator): boolean {
    return [
        PropertyOperator.GreaterThan,
        PropertyOperator.GreaterThanOrEqual,
        PropertyOperator.LessThan,
        PropertyOperator.LessThanOrEqual,
        PropertyOperator.Between,
        PropertyOperator.NotBetween,
    ].includes(operator)
}

export function isOperatorDate(operator: PropertyOperator): boolean {
    return [PropertyOperator.IsDateBefore, PropertyOperator.IsDateAfter, PropertyOperator.IsDateExact].includes(
        operator
    )
}

/** Compare objects deeply. */
export function objectsEqual(obj1: any, obj2: any): boolean {
    return equal(obj1, obj2)
}

export function isString(candidate: unknown): candidate is string {
    return typeof candidate === 'string'
}

export function isObject(candidate: unknown): candidate is Record<string, unknown> {
    return typeof candidate === 'object' && candidate !== null
}

export function isEmptyObject(candidate: unknown): boolean {
    return isObject(candidate) && Object.keys(candidate).length === 0
}

export function isNonEmptyObject(candidate: unknown): candidate is Record<string, unknown> {
    return isObject(candidate) && !isEmptyObject(candidate)
}

// https://stackoverflow.com/questions/25421233/javascript-removing-undefined-fields-from-an-object
export function objectClean<T extends Record<string | number | symbol, unknown>>(obj: T): T {
    const response = { ...obj }
    Object.keys(response).forEach((key) => {
        if (response[key] === undefined) {
            delete response[key]
        }
    })
    return response
}
export function objectCleanWithEmpty<T extends Record<string | number | symbol, unknown>>(
    obj: T,
    ignoredKeys: string[] = []
): T {
    const response = { ...obj }
    Object.keys(response)
        .filter((key) => !ignoredKeys.includes(key))
        .forEach((key) => {
            // remove undefined values
            if (response[key] === undefined) {
                delete response[key]
            }
            // remove empty arrays i.e. []
            if (
                typeof response[key] === 'object' &&
                Array.isArray(response[key]) &&
                (response[key] as unknown[]).length === 0
            ) {
                delete response[key]
            }
            // remove empty objects i.e. {}
            if (
                typeof response[key] === 'object' &&
                !Array.isArray(response[key]) &&
                response[key] !== null &&
                Object.keys(response[key] as Record<string | number | symbol, unknown>).length === 0
            ) {
                delete response[key]
            }
        })
    return response
}

export const removeUndefinedAndNull = (obj: any): any => {
    if (Array.isArray(obj)) {
        return obj.map(removeUndefinedAndNull)
    } else if (obj && typeof obj === 'object') {
        return Object.entries(obj).reduce((acc, [key, value]) => {
            if (value !== undefined && value !== null) {
                acc[key] = removeUndefinedAndNull(value)
            }
            return acc
        }, {} as Record<string, any>)
    }
    return obj
}

/** Returns "response" from: obj2 = { ...obj1, ...response }  */
export function objectDiffShallow(obj1: Record<string, any>, obj2: Record<string, any>): Record<string, any> {
    const response: Record<string, any> = { ...obj2 }
    for (const key of Object.keys(obj1)) {
        if (key in response) {
            if (obj1[key] === response[key]) {
                delete response[key]
            }
        } else {
            response[key] = undefined
        }
    }
    return response
}

export function idToKey(array: Record<string, any>[], keyField: string = 'id'): Record<string, any> {
    const object: Record<string, any> = {}
    for (const element of array) {
        object[element[keyField]] = element
    }
    return object
}

export function makeDelay(ms: number): () => Promise<void> {
    return () => delay(ms)
}

export function delay(ms: number, signal?: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
        const timeoutId = setTimeout(resolve, ms)
        if (signal) {
            signal.addEventListener('abort', () => {
                clearTimeout(timeoutId)
                reject(new DOMException('Aborted', 'AbortError'))
            })
        }
    })
}

export function clearDOMTextSelection(): void {
    if (window.getSelection) {
        if (window.getSelection()?.empty) {
            // Chrome
            window.getSelection()?.empty()
        } else if (window.getSelection()?.removeAllRanges) {
            // Firefox
            window.getSelection()?.removeAllRanges()
        }
    } else if ((document as any).selection) {
        // IE?
        ;(document as any).selection.empty()
    }
}

export function slugify(text: string): string {
    return text
        .toString() // Cast to string
        .toLowerCase() // Convert the string to lowercase letters
        .normalize('NFD') // The normalize() method returns the Unicode Normalization Form of a given string.
        .trim() // Remove whitespace from both sides of a string
        .replace(/\s+/g, '-') // Replace spaces with -
        .replace(/[^\w-]+/g, '') // Remove all non-word chars
        .replace(/--+/g, '-')
}

export const DEFAULT_DECIMAL_PLACES = 2

/** Format number with comma as the thousands separator. */
export function humanFriendlyNumber(
    d: number,
    maximumFractionDigits: number = DEFAULT_DECIMAL_PLACES,
    minimumFractionDigits: number = 0
): string {
    if (isNaN(maximumFractionDigits) || maximumFractionDigits < 0) {
        maximumFractionDigits = DEFAULT_DECIMAL_PLACES
    }
    if (isNaN(minimumFractionDigits) || minimumFractionDigits < 0) {
        minimumFractionDigits = 0
    }

    return d.toLocaleString('en-US', { maximumFractionDigits, minimumFractionDigits })
}

export function humanFriendlyLargeNumber(d: number): string {
    if (isNaN(d)) {
        return 'NaN'
    } else if (!isFinite(d)) {
        if (d > 0) {
            return 'inf'
        }
        return '-inf'
    }
    const trillion = 1_000_000_000_000
    const billion = 1_000_000_000
    const million = 1_000_000
    const thousand = 1_000

    // handle positive number only to make life easier
    const prefix = d >= 0 ? '' : '-'
    d = Math.abs(d)

    // round to 3 significant figures
    d = parseFloat(d.toPrecision(3))

    if (d >= trillion) {
        return `${prefix}${(d / trillion).toString()}T`
    } else if (d >= billion) {
        return `${prefix}${(d / billion).toString()}B`
    }
    if (d >= million) {
        return `${prefix}${(d / million).toString()}M`
    }
    if (d >= thousand) {
        return `${prefix}${(d / thousand).toString()}K`
    }
    return `${prefix}${d}`
}

/** Format currency from string with commas and a number of decimal places (defaults to 2). */
export function humanFriendlyCurrency(d: string | undefined | number, precision: number = 2): string {
    if (!d) {
        d = '0.00'
    }

    let number: number
    if (typeof d === 'string') {
        number = parseFloat(d)
    } else {
        number = d
    }

    return `$${number.toLocaleString('en-US', { maximumFractionDigits: precision, minimumFractionDigits: precision })}`
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
    formatTime = 'h:mm:ss A'
): string {
    if (!date) {
        return 'Never'
    }
    const parsedDate = dayjs(date)
    const today = dayjs().startOf('day')
    const yesterday = today.clone().subtract(1, 'days').startOf('day')
    if (parsedDate.isSame(dayjs(), 'm')) {
        return 'Just now'
    }
    let formatString: string
    if (parsedDate.isSame(today, 'd')) {
        formatString = `[Today] ${formatTime}`
    } else if (parsedDate.isSame(yesterday, 'd')) {
        formatString = `[Yesterday] ${formatTime}`
    } else {
        formatString = `${formatDate} ${formatTime}`
    }
    return parsedDate.format(formatString)
}

// Pad numbers with leading zeros
export const zeroPad = (num: number, places: number): string => String(num).padStart(places, '0')

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
    const regexp = /^(https?:|mailto:)/
    return !!input.trim().match(regexp)
}

export function isEmail(string: string): boolean {
    if (!string) {
        return false
    }
    // https://html.spec.whatwg.org/multipage/input.html#valid-e-mail-address
    const regexp =
        /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/
    return !!string.match?.(regexp)
}

export function truncate(str: string, maxLength: number): string {
    return str.length > maxLength ? str.slice(0, maxLength - 1) + '...' : str
}

export function eventToDescription(
    event: Pick<EventType, 'elements' | 'event' | 'properties'>,
    shortForm: boolean = false
): string {
    if (['$pageview', '$pageleave'].includes(event.event)) {
        return event.properties.$pathname ?? event.properties.$current_url ?? '<unknown URL>'
    }
    if (event.event === '$autocapture') {
        return autoCaptureEventToDescription(event, shortForm)
    }
    // All other events and actions
    return event.event
}

// $event_type to verb map
const eventTypeToVerb: { [key: string]: string } = {
    click: 'clicked',
    change: 'typed something into',
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
        key: 'This month',
        values: ['mStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('month'), date.endOf('month')),
        defaultInterval: 'day',
    },
    {
        key: 'Previous month',
        values: ['-1mStart', '-1mEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string =>
            formatDateRange(date.subtract(1, 'month').startOf('month'), date.subtract(1, 'month').endOf('month')),
        inactive: true,
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
} as const

export function dateFilterToText(
    dateFrom: string | dayjs.Dayjs | null | undefined,
    dateTo: string | dayjs.Dayjs | null | undefined,
    defaultValue: string | null,
    dateOptions: DateMappingOption[] = dateMapping,
    isDateFormatted: boolean = false,
    dateFormat: string = DATE_FORMAT,
    startOfRange: boolean = false
): string | null {
    if (dayjs.isDayjs(dateFrom) && dayjs.isDayjs(dateTo)) {
        return formatDateRange(dateFrom, dateTo, dateFormat)
    }
    dateFrom = (dateFrom || undefined) as string | undefined
    dateTo = (dateTo || undefined) as string | undefined

    if (isDate.test(dateFrom || '') && isDate.test(dateTo || '')) {
        return isDateFormatted
            ? formatDateRange(dayjs(dateFrom, 'YYYY-MM-DD'), dayjs(dateTo, 'YYYY-MM-DD'))
            : `${dateFrom} - ${dateTo}`
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
            return isDateFormatted && getFormattedDate ? getFormattedDate(dayjs(), dateFormat) : key
        }
    }

    if (dateFrom) {
        const dateOption: (typeof dateOptionsMap)[keyof typeof dateOptionsMap] = dateOptionsMap[dateFrom.slice(-1)]
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
    const dateOption: (typeof dateOptionsMap)[keyof typeof dateOptionsMap] = dateOptionsMap[dateFrom.slice(-1)]
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
    const unit = dateOptionsMap[rawUnit] || 'day'
    return { amount, unit, clip: clip as 'Start' | 'End' }
}

export function componentsToDayJs({ amount, unit, clip }: DateComponents, offset?: Dayjs): Dayjs {
    const dayjsInstance = offset ?? dayjs()
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
export function dateStringToDayJs(date: string | null): dayjs.Dayjs | null {
    if (isDate.test(date || '')) {
        return dayjs(date)
    }
    const dateComponents = dateStringToComponents(date)
    if (!dateComponents) {
        return null
    }
    const offset: dayjs.Dayjs = dayjs().startOf('day')
    const response = componentsToDayJs(dateComponents, offset)
    return response
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

    if (parsedDateFrom?.unit === 'day' || parsedDateTo?.unit === 'day' || dateFrom === 'mStart') {
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
    }
    throw new UnexpectedNeverError(interval)
}

const defaultDatesForInterval = {
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

export function clamp(value: number, min: number, max: number): number {
    return value > max ? max : value < min ? min : value
}

export function isMobile(): boolean {
    return navigator.userAgent.includes('Mobile')
}

export function isMac(): boolean {
    return navigator.platform.includes('Mac')
}

export function platformCommandControlKey(modifier: string): string {
    return `${isMac() ? '⌘' : 'Ctrl + '}${modifier}`
}

export function groupBy<T>(items: T[], groupResolver: (item: T) => string | number): Record<string | number, T[]> {
    const itemsGrouped: Record<string | number, T[]> = {}
    for (const item of items) {
        const group = groupResolver(item)
        if (!(group in itemsGrouped)) {
            itemsGrouped[group] = []
        } // Ensure there's an array to push to
        itemsGrouped[group].push(item)
    }
    return itemsGrouped
}

export function uniqueBy<T>(items: T[], uniqueResolver: (item: T) => any): T[] {
    const uniqueKeysSoFar = new Set<string>()
    const itemsUnique: T[] = []
    for (const item of items) {
        const uniqueKey = uniqueResolver(item)
        if (!uniqueKeysSoFar.has(uniqueKey)) {
            uniqueKeysSoFar.add(uniqueKey)
            itemsUnique.push(item)
        }
    }
    return itemsUnique
}

export function sample<T>(items: T[], size: number): T[] {
    if (!items.length) {
        throw Error('Items array is empty!')
    }
    if (size > items.length) {
        throw Error('Sample size cannot exceed items array length!')
    }
    const results: T[] = []
    const internalItems = [...items]
    if (size === items.length) {
        return internalItems
    }
    for (let i = 0; i < size; i++) {
        const index = Math.floor(Math.random() * internalItems.length)
        results.push(internalItems[index])
        internalItems.splice(index, 1)
    }
    return results
}

export function sampleOne<T>(items: T[]): T {
    if (!items.length) {
        throw Error('Items array is empty!')
    }
    const index = inStorybookTestRunner() ? 0 : Math.floor(Math.random() * items.length)
    return items[index]
}

/** Convert camelCase, PascalCase or snake_case to Sentence case or Title Case. */
export function identifierToHuman(identifier: string | number, caseType: 'sentence' | 'title' = 'sentence'): string {
    const words: string[] = []
    let currentWord: string = ''
    String(identifier)
        .trim()
        .split('')
        .forEach((character) => {
            if (character === '_' || character === '-') {
                if (currentWord) {
                    words.push(currentWord)
                }
                currentWord = ''
            } else if (
                character === character.toLowerCase() &&
                (!'0123456789'.includes(character) ||
                    (currentWord && '0123456789'.includes(currentWord[currentWord.length - 1])))
            ) {
                currentWord += character
            } else {
                if (currentWord) {
                    words.push(currentWord)
                }
                currentWord = character.toLowerCase()
            }
        })
    if (currentWord) {
        words.push(currentWord)
    }
    return capitalizeFirstLetter(
        words.map((word) => (caseType === 'sentence' ? word : capitalizeFirstLetter(word))).join(' ')
    )
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

export function someParentMatchesSelector(element: HTMLElement, selector: string): boolean {
    if (element.matches(selector)) {
        return true
    }
    return element.parentElement ? someParentMatchesSelector(element.parentElement, selector) : false
}

export function hashCodeForString(s: string): number {
    /* Hash function that returns a number for a given string. Useful for using the same colors for tags or avatars.
    Forked from https://github.com/segmentio/evergreen/
    */
    let hash = 0
    if (s.trim().length === 0) {
        return hash
    }
    for (let i = 0; i < s.length; i++) {
        const char = s.charCodeAt(i)
        hash = (hash << 5) - hash + char
        hash &= hash // Convert to 32bit integer
    }
    return Math.abs(hash)
}

export function colorForString(s: string): LemonTagType {
    /*
    Returns a color name for a given string, where the color will always be the same for the same string.
    */
    return tagColors[hashCodeForString(s) % tagColors.length]
}

/** Truncates a string (`input`) in the middle. `maxLength` represents the desired maximum length of the output. */
export function midEllipsis(input: string, maxLength: number): string {
    if (input.length <= maxLength) {
        return input
    }

    const middle = Math.ceil(input.length / 2)
    const excessLeft = Math.ceil((input.length - maxLength) / 2)
    const excessRight = Math.ceil((input.length - maxLength + 1) / 2)
    return `${input.slice(0, middle - excessLeft)}…${input.slice(middle + excessRight)}`
}

export function pluralize(count: number, singular: string, plural?: string, includeNumber: boolean = true): string {
    if (!plural) {
        plural = singular + 's'
    }
    const form = count === 1 ? singular : plural
    return includeNumber ? `${humanFriendlyNumber(count)} ${form}` : form
}

const WORD_PLURALIZATION_RULES = [
    [/s?$/i, 's'],
    [/([^aeiou]ese)$/i, '$1'],
    [/(ax|test)is$/i, '$1es'],
    [/(alias|[^aou]us|t[lm]as|gas|ris)$/i, '$1es'],
    [/(e[mn]u)s?$/i, '$1s'],
    [/([^l]ias|[aeiou]las|[ejzr]as|[iu]am)$/i, '$1'],
    [/(alumn|syllab|vir|radi|nucle|fung|cact|stimul|termin|bacill|foc|uter|loc|strat)(?:us|i)$/i, '$1i'],
    [/(alumn|alg|vertebr)(?:a|ae)$/i, '$1ae'],
    [/(seraph|cherub)(?:im)?$/i, '$1im'],
    [/(her|at|gr)o$/i, '$1oes'],
    [
        /(agend|addend|millenni|dat|extrem|bacteri|desiderat|strat|candelabr|errat|ov|symposi|curricul|automat|quor)(?:a|um)$/i,
        '$1a',
    ],
    [/(apheli|hyperbat|periheli|asyndet|noumen|phenomen|criteri|organ|prolegomen|hedr|automat)(?:a|on)$/i, '$1a'],
    [/sis$/i, 'ses'],
    [/(?:(kni|wi|li)fe|(ar|l|ea|eo|oa|hoo)f)$/i, '$1$2ves'],
    [/([^aeiouy]|qu)y$/i, '$1ies'],
    [/([^ch][ieo][ln])ey$/i, '$1ies'],
    [/(x|ch|ss|sh|zz)$/i, '$1es'],
    [/(matr|cod|mur|sil|vert|ind|append)(?:ix|ex)$/i, '$1ices'],
    [/\b((?:tit)?m|l)(?:ice|ouse)$/i, '$1ice'],
    [/(pe)(?:rson|ople)$/i, '$1ople'],
    [/(child)(?:ren)?$/i, '$1ren'],
    [/eaux$/i, '$0'],
    [/m[ae]n$/i, 'men'],
] as [RegExp, string][]

export function wordPluralize(word: string): string {
    let len = WORD_PLURALIZATION_RULES.length

    // Iterate over the sanitization rules and use the first one to match.
    while (len--) {
        const [regex, replacement] = WORD_PLURALIZATION_RULES[len]
        if (regex.test(word)) {
            return word.replace(regex, replacement)
        }
    }

    return word
}

const COMPACT_NUMBER_MAGNITUDES = ['', 'K', 'M', 'B', 'T', 'P', 'E', 'Z', 'Y']

/** Return a number in a compact format, with a SI suffix if applicable.
 *  Server-side equivalent: utils.py#compact_number.
 */
export function compactNumber(value: number | null): string {
    if (value === null) {
        return '-'
    }

    value = parseFloat(value.toPrecision(3))
    let magnitude = 0
    while (Math.abs(value) >= 1000) {
        magnitude++
        value /= 1000
    }
    return magnitude > 0 ? `${value} ${COMPACT_NUMBER_MAGNITUDES[magnitude]}` : value.toString()
}

export function roundToDecimal(value: number | null, places: number = 2): string {
    if (value === null) {
        return '-'
    }
    return (Math.round(value * 100) / 100).toFixed(places)
}

export function sortedKeys<T extends Record<string, any> = Record<string, any>>(object: T): T {
    const newObject: T = {} as T
    for (const key of Object.keys(object).sort()) {
        newObject[key as keyof T] = object[key]
    }
    return newObject
}

export const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')

export function endWithPunctation(text?: string | null): string {
    let trimmedText = text?.trim()
    if (!trimmedText) {
        return ''
    }
    if (!/[.!?]$/.test(trimmedText)) {
        trimmedText += '.'
    }
    return trimmedText
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

/** Join array of string into a list ("a, b, and c"). Uses the Oxford comma, but only if there are at least 3 items. */
export function humanList(arr: readonly string[]): string {
    return arr.length > 2 ? arr.slice(0, -1).join(', ') + ', and ' + arr.at(-1) : arr.join(' and ')
}

export function resolveWebhookService(webhookUrl: string): string {
    for (const [service, domain] of Object.entries(WEBHOOK_SERVICES)) {
        if (webhookUrl.includes(domain + '/')) {
            return service
        }
    }
    return 'your webhook service'
}

export function hexToRGB(hex: string): { r: number; g: number; b: number; a: number } {
    // Remove the "#" if it exists
    hex = hex.replace(/^#/, '')

    // Handle shorthand notation (e.g., "#123" => "#112233")
    if (hex.length === 3 || hex.length === 4) {
        hex = hex
            .split('')
            .map((char) => char + char)
            .join('')
    }

    if (hex.length !== 6 && hex.length !== 8) {
        console.warn(`Incorrectly formatted color string: ${hex}.`)
        return { r: 0, g: 0, b: 0, a: 0 }
    }

    // Extract the rgb values
    const r = parseInt(hex.slice(0, 2), 16)
    const g = parseInt(hex.slice(2, 4), 16)
    const b = parseInt(hex.slice(4, 6), 16)
    const a = hex.length === 8 ? parseInt(hex.slice(6, 8), 16) / 255 : 1

    return { r, g, b, a }
}

export function hexToRGBA(hex: string, alpha = 1): string {
    /**
     * Returns an RGBA string with specified alpha if the hex string is valid.
     * @param hex e.g. '#FF0000'
     * @param alpha e.g. 0.5
     */

    const { r, g, b } = hexToRGB(hex)
    const a = alpha
    return `rgba(${[r, g, b, a].join(',')})`
}

export function RGBToHex(rgb: string): string {
    const rgbValues = rgb.replace('rgb(', '').replace(')', '').split(',').map(Number)

    return `#${rgbValues.map((val) => val.toString(16).padStart(2, '0')).join('')}`
}

export function RGBToRGBA(rgb: string, a: number): string {
    const [r, g, b] = rgb.slice(4, rgb.length - 1).split(',')
    return `rgba(${[r, g, b, a].join(',')})`
}

export function RGBToHSL(r: number, g: number, b: number): { h: number; s: number; l: number } {
    // Convert RGB values to the range 0-1
    r /= 255
    g /= 255
    b /= 255

    // Find min and max values of r, g, b
    const max = Math.max(r, g, b)
    const min = Math.min(r, g, b)
    const delta = max - min

    // Calculate lightness
    let h = 0,
        s = 0
    const l = (max + min) / 2

    if (delta !== 0) {
        // Calculate saturation
        s = l < 0.5 ? delta / (max + min) : delta / (2 - max - min)

        // Calculate hue
        switch (max) {
            case r:
                h = ((g - b) / delta + (g < b ? 6 : 0)) % 6
                break
            case g:
                h = (b - r) / delta + 2
                break
            case b:
                h = (r - g) / delta + 4
                break
        }
        h *= 60 // Convert hue to degrees
    }

    return {
        h: Math.round(h),
        s: Math.round(s * 100),
        l: Math.round(l * 100),
    }
}

export function lightenDarkenColor(hex: string, pct: number): string {
    /**
     * Returns a lightened or darkened color, similar to SCSS darken()
     * @param hex e.g. '#FF0000'
     * @param pct percentage amount to lighten or darken, e.g. -20
     */

    function output(val: number): number {
        return Math.max(0, Math.min(255, val))
    }

    const amt = Math.round(2.55 * pct)
    let { r, g, b } = hexToRGB(hex)

    r = output(r + amt)
    g = output(g + amt)
    b = output(b + amt)

    return `rgb(${[r, g, b].join(',')})`
}

/**
 * Gradate color saturation based on its intended strength.
 * This is for visualizations where a data point's color depends on its value.
 * @param color A HEX color to gradate.
 * @param strength The strength of the data point.
 * @param floor The minimum saturation. This preserves proportionality of strength, so doesn't just cut it off.
 */
export function gradateColor(
    color: string,
    strength: number,
    floor: number = 0
): `hsla(${number}, ${number}%, ${number}%, ${string})` {
    const { r, g, b } = hexToRGB(color)
    const { h, s, l } = RGBToHSL(r, g, b)

    const saturation = floor + (1 - floor) * strength
    return `hsla(${h}, ${s}%, ${l}%, ${saturation.toPrecision(3)})`
}

export function toString(input?: any): string {
    return input?.toString() || ''
}

export function average(input: number[]): number {
    /**
     * Returns the average of an array
     * @param input e.g. [100,50, 75]
     */
    return Math.round((input.reduce((acc, val) => acc + val, 0) / input.length) * 10) / 10
}

export function median(input: number[]): number {
    /**
     * Returns the median of an array
     * @param input e.g. [3,7,10]
     */
    const sorted = [...input].sort((a, b) => a - b)
    const half = Math.floor(sorted.length / 2)

    if (sorted.length % 2) {
        return sorted[half]
    }
    return average([sorted[half - 1], sorted[half]])
}

export function sum(input: number[]): number {
    return input.reduce((a, b) => a + b, 0)
}

export function validateJson(value: string): boolean {
    try {
        JSON.parse(value)
        return true
    } catch {
        return false
    }
}

export function tryJsonParse(value: string, fallback?: any): any {
    try {
        return JSON.parse(value)
    } catch {
        return fallback
    }
}

export function validateJsonFormItem(_: any, value: string): Promise<string | void> {
    return validateJson(value) ? Promise.resolve() : Promise.reject('Not valid JSON!')
}

export function ensureStringIsNotBlank(s?: string | null): string | null {
    return typeof s === 'string' && s.trim() !== '' ? s : null
}

export function isMultiSeriesFormula(formula?: string | null): boolean {
    if (!formula) {
        return false
    }
    const count = (formula.match(/[a-zA-Z]/g) || []).length
    return count > 1
}

export function floorMsToClosestSecond(ms: number): number {
    return Math.floor(ms / 1000) * 1000
}

export function ceilMsToClosestSecond(ms: number): number {
    return Math.ceil(ms / 1000) * 1000
}

// https://stackoverflow.com/questions/40929260/find-last-index-of-element-inside-array-by-certain-condition
export function findLastIndex<T>(array: Array<T>, predicate: (value: T, index: number, obj: T[]) => boolean): number {
    let l = array.length
    while (l--) {
        if (predicate(array[l], l, array)) {
            return l
        }
    }
    return -1
}

export function isEllipsisActive(e: HTMLElement | null): boolean {
    return !!e && e.offsetWidth < e.scrollWidth
}

export function isGroupType(actor: ActorType): actor is GroupActorType {
    return actor.type === 'group'
}

export function getEventNamesForAction(actionId: string | number, allActions: ActionType[]): string[] {
    const id = parseInt(String(actionId))
    return allActions
        .filter((a) => a.id === id)
        .flatMap((a) => a.steps?.filter((step) => step.event).map((step) => String(step.event)) as string[])
}

export const isUserLoggedIn = (): boolean => !getAppContext()?.anonymous

/** Sorting function for Array.prototype.sort that works for numbers and strings automatically. */
export const autoSorter = (a: any, b: any): number => {
    return typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b))
}

// https://stackoverflow.com/questions/175739/how-can-i-check-if-a-string-is-a-valid-number
export function isNumeric(x: any): boolean {
    if (typeof x === 'number') {
        return true
    }
    if (typeof x != 'string') {
        return false
    }
    return !isNaN(Number(x)) && !isNaN(parseFloat(x))
}

/**
 * Check if the argument is nullish (null or undefined).
 *
 * Useful as a typeguard, e.g. when passed to Array.filter()
 *
 * @example
 * const myList = [1, 2, null]; // type is (number | null)[]
 *
 * // using isNotNil
 * const myFilteredList1 = myList.filter(isNotNil) // type is number[]
 * const squaredList1 = myFilteredList1.map(x => x * x) // not a type error!
 *
 * // compared to:
 * const myFilteredList2 = myList.filter(x => x != null) // type is (number | null)[]
 * const squaredList2 = myFilteredList2.map(x => x * x) // Type Error: TS18047: x is possibly null
 */
export function isNotNil<T>(arg: T): arg is Exclude<T, null | undefined> {
    return arg !== null && arg !== undefined
}

/** An error signaling that a value of type `never` in TypeScript was used unexpectedly at runtime.
 *
 * Useful for type-narrowing, will give a compile-time error if the type of x is not `never`.
 * See the example below where it catches a missing branch at compile-time.
 *
 * @example
 *
 * enum MyEnum {
 *     a,
 *     b,
 * }
 *
 * function handleEnum(x: MyEnum) {
 *     switch (x) {
 *         case MyEnum.a:
 *             return
 *         // missing branch
 *         default:
 *             throw new UnexpectedNeverError(x) // TS2345: Argument of type MyEnum is not assignable to parameter of type never
 *     }
 * }
 *
 * function handleEnum(x: MyEnum) {
 *     switch (x) {
 *         case MyEnum.a:
 *             return
 *         case MyEnum.b:
 *             return
 *         default:
 *             throw new UnexpectedNeverError(x) // no type error
 *     }
 * }
 *
 */
export class UnexpectedNeverError extends Error {
    constructor(x: never, message?: string) {
        message = message ?? 'Unexpected never: ' + String(x)
        super(message)

        // restore prototype chain, which is broken by Error
        // see https://stackoverflow.com/questions/41102060/typescript-extending-error-class
        const actualProto = new.target.prototype
        if (Object.setPrototypeOf) {
            Object.setPrototypeOf(this, actualProto)
        }
    }
}

export function promiseResolveReject<T>(): {
    resolve: (value: T) => void
    reject: (reason?: any) => void
    promise: Promise<T>
} {
    let resolve: (value: T) => void
    let reject: (reason?: any) => void
    const promise = new Promise<T>((innerResolve, innerReject) => {
        resolve = innerResolve
        reject = innerReject
    })
    return { resolve: resolve!, reject: reject!, promise }
}

export type AsyncReturnType<T extends (...args: any) => any> = T extends (...args: any) => Promise<infer R> ? R : any

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

export function range(startOrEnd: number, end?: number): number[] {
    let length = startOrEnd
    let start = 0
    if (typeof end == 'number') {
        start = startOrEnd
        length = end - start
    }
    return Array.from({ length }, (_, i) => i + start)
}

export function interleave(arr: any[], delimiter: any): any[] {
    return arr.flatMap((item, index, _arr) =>
        _arr.length - 1 !== index // check for the last item
            ? [item, delimiter]
            : item
    )
}

export function downloadFile(file: File): void {
    // Create a link and set the URL using `createObjectURL`
    const link = document.createElement('a')
    link.style.display = 'none'
    link.href = URL.createObjectURL(file)
    link.download = file.name

    // It needs to be added to the DOM so it can be clicked
    document.body.appendChild(link)
    link.click()

    // To make this work on Firefox we need to wait
    // a little while before removing it.
    setTimeout(() => {
        URL.revokeObjectURL(link.href)
        link?.parentNode?.removeChild(link)
    }, 0)
}

export function inStorybookTestRunner(): boolean {
    return navigator.userAgent.includes('StorybookTestRunner')
}

export function inStorybook(): boolean {
    return '__STORYBOOK_CLIENT_API__' in window
}

/** We issue a cancel request, when the request is aborted or times out (frontend side), since in these cases the backend query might still be running. */
export function shouldCancelQuery(error: any): boolean {
    return isAbortedRequest(error) || isTimedOutRequest(error)
}

export function isAbortedRequest(error: any): boolean {
    return error.name === 'AbortError' || error.message?.name === 'AbortError'
}

export function isTimedOutRequest(error: any): boolean {
    return error.status === 504
}

export function flattenObject(ob: Record<string, any>): Record<string, any> {
    const toReturn = {}

    for (const i in ob) {
        if (!ob.hasOwnProperty(i)) {
            continue
        }

        if (typeof ob[i] == 'object') {
            const flatObject = flattenObject(ob[i])
            for (const x in flatObject) {
                if (!flatObject.hasOwnProperty(x)) {
                    continue
                }

                let j = i
                if (i.match(/\d+/)) {
                    // Pad integer values for better sorting
                    j = i.padStart(3, '0')
                }

                toReturn[j + '.' + x] = flatObject[x]
            }
        } else {
            toReturn[i] = ob[i]
        }
    }
    return toReturn
}

export const shouldIgnoreInput = (e: KeyboardEvent): boolean => {
    return (
        ['input', 'textarea'].includes((e.target as HTMLElement).tagName.toLowerCase()) ||
        (e.target as HTMLElement).isContentEditable ||
        (e.target as HTMLElement).parentElement?.isContentEditable ||
        false
    )
}

export const base64Encode = (str: string): string => {
    const data = new TextEncoder().encode(str)
    const binString = Array.from(data, (byte) => String.fromCharCode(byte)).join('')
    return btoa(binString)
}

export const base64Decode = (encodedString: string): string => {
    const data = base64ToUint8Array(encodedString)
    return new TextDecoder().decode(data)
}

export const base64ArrayBuffer = (encodedString: string): ArrayBuffer => {
    const data = base64ToUint8Array(encodedString)
    return data.buffer
}

export const base64ToUint8Array = (encodedString: string): Uint8Array => {
    const binString = atob(encodedString)
    const data = new Uint8Array(binString.length)
    for (let i = 0; i < binString.length; i++) {
        data[i] = binString.charCodeAt(i)
    }
    return data
}

export function hasFormErrors(object: any): boolean {
    if (Array.isArray(object)) {
        return object.some(hasFormErrors)
    } else if (typeof object === 'object' && object !== null) {
        return Object.values(object).some(hasFormErrors)
    }
    return !!object
}

export function debounce<F extends (...args: Parameters<F>) => ReturnType<F>>(
    func: F,
    waitFor: number
): (...args: Parameters<F>) => void {
    let timeout: ReturnType<typeof setTimeout>
    return (...args: Parameters<F>): void => {
        clearTimeout(timeout)
        timeout = setTimeout(() => func(...args), waitFor)
    }
}

export function interleaveArray<T1, T2>(arr: T1[], separator: T2): (T1 | T2)[] {
    return arr.flatMap((item, index, _arr) => (_arr.length - 1 !== index ? [item, separator] : [item]))
}

/**
 * Uses the non-standard `memory` extension available in Chromium based browsers to
 * get JS heap metrics.
 */
export const getJSHeapMemory = (): {
    js_heap_used_mb?: number
    js_heap_total_mb?: number
    js_heap_limit_mb?: number
} => {
    if ('memory' in window.performance) {
        const memory = (window.performance as any).memory
        return {
            js_heap_used_mb: +(memory.usedJSHeapSize / 1024 / 1024).toFixed(2),
            js_heap_total_mb: +(memory.totalJSHeapSize / 1024 / 1024).toFixed(2),
            js_heap_limit_mb: +(memory.jsHeapSizeLimit / 1024 / 1024).toFixed(2),
        }
    }
    return {}
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

    // Root-relative path
    if (decoded.startsWith('/')) {
        return decoded
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
