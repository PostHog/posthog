import React, { CSSProperties, PropsWithChildren } from 'react'
import api from './api'
import {
    ActionFilter,
    ActionType,
    ActorType,
    AnyCohortCriteriaType,
    AnyPropertyFilter,
    BehavioralCohortType,
    BehavioralEventType,
    CohortCriteriaGroupFilter,
    CohortType,
    dateMappingOption,
    EventType,
    FilterLogicalOperator,
    FilterType,
    GroupActorType,
    IntervalType,
    PropertyFilter,
    PropertyFilterValue,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
    PropertyType,
    TimeUnitType,
} from '~/types'
import equal from 'fast-deep-equal'
import { tagColors } from 'lib/colors'
import { WEBHOOK_SERVICES } from 'lib/constants'
import { KeyMappingInterface } from 'lib/components/PropertyKeyInfo'
import { AlignType } from 'rc-trigger/lib/interface'
import { dayjs } from 'lib/dayjs'
import { Spinner } from './components/Spinner/Spinner'
import { getAppContext } from './utils/getAppContext'
import { isValidPropertyFilter } from './components/PropertyFilters/utils'
import { IconCopy } from './components/icons'
import { lemonToast } from './components/lemonToast'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'

export const ANTD_TOOLTIP_PLACEMENTS: Record<any, AlignType> = {
    // `@yiminghe/dom-align` objects
    // https://github.com/react-component/select/blob/dade915d81069b8d3b3b5679bb9daee7e992faba/src/SelectTrigger.jsx#L11-L28
    bottomLeft: {
        points: ['tl', 'bl'],
        offset: [0, 4],
        overflow: {
            adjustX: 0,
            adjustY: 0,
        },
    },
    bottomRight: {
        points: ['tr', 'br'],
        offset: [0, 4],
        overflow: {
            adjustX: 0,
            adjustY: 0,
        },
    },
    topLeft: {
        points: ['bl', 'tl'],
        offset: [0, -4],
        overflow: {
            adjustX: 0,
            adjustY: 0,
        },
    },
    horizontalPreferRight: {
        points: ['cl', 'cr'],
        offset: [4, 0],
        overflow: {
            adjustX: true,
            adjustY: false,
        },
    },
}

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
export const humanizeBytes = (fileSizeInBytes: number): string => {
    let i = -1
    const byteUnits = [' kB', ' MB', ' GB', ' TB', 'PB', 'EB', 'ZB', 'YB']
    do {
        fileSizeInBytes = fileSizeInBytes / 1024
        i++
    } while (fileSizeInBytes > 1024)

    return Math.max(fileSizeInBytes, 0.1).toFixed(1) + byteUnits[i]
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
              .slice(1)
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

/** Return percentage from number, e.g. 0.234 is 23.4%. */
export function percentage(
    division: number,
    maximumFractionDigits: number = 2,
    fixedPrecision: boolean = false
): string {
    return division
        .toLocaleString('en-US', {
            style: 'percent',
            maximumFractionDigits,
            minimumFractionDigits: fixedPrecision ? maximumFractionDigits : undefined,
        })
        .replace(',', ' ') // Use space as thousands separator as it's more international
}

export function Loading(props: Record<string, any>): JSX.Element {
    return (
        <div className="loading-overlay" style={props.style}>
            <Spinner size="lg" />
        </div>
    )
}

export function deleteWithUndo({
    undo = false,
    ...props
}: {
    undo?: boolean
    endpoint: string
    object: Record<string, any>
    callback?: () => void
}): void {
    api.update(`api/${props.endpoint}/${props.object.id}`, {
        ...props.object,
        deleted: !undo,
    }).then(() => {
        props.callback?.()
        lemonToast[undo ? 'success' : 'info'](
            <>
                <b>{props.object.name || <i>{props.object.derived_name || 'Unnamed'}</i>}</b> has been{' '}
                {undo ? 'restored' : 'deleted'}
            </>,
            {
                toastId: `delete-item-${props.object.id}-${undo}`,
                button: undo
                    ? undefined
                    : {
                          label: 'Undo',
                          action: () => deleteWithUndo({ undo: true, ...props }),
                      },
            }
        )
    })
}

export function DeleteWithUndo(
    props: PropsWithChildren<{
        endpoint: string
        object: {
            name?: string
            id: number
        }
        className: string
        style: CSSProperties
        callback: () => void
    }>
): JSX.Element {
    const { className, style, children } = props
    return (
        <a
            href="#"
            onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                deleteWithUndo(props)
            }}
            className={className}
            style={style}
        >
            {children}
        </a>
    )
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

export function capitalizeFirstLetter(string: string): string {
    return string.charAt(0).toUpperCase() + string.slice(1)
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

export const allOperatorsMapping: Record<string, string> = {
    ...dateTimeOperatorMap,
    ...stringOperatorMap,
    ...numericOperatorMap,
    ...genericOperatorMap,
    ...booleanOperatorMap,
    ...durationOperatorMap,
    // slight overkill to spread all of these into the map
    // but gives freedom for them to diverge more over time
}

const operatorMappingChoice: Record<keyof typeof PropertyType, Record<string, string>> = {
    DateTime: dateTimeOperatorMap,
    String: stringOperatorMap,
    Numeric: numericOperatorMap,
    Boolean: booleanOperatorMap,
    Duration: durationOperatorMap,
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
    return [PropertyOperator.IsSet, PropertyOperator.IsNotSet].includes(operator)
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

export function formatPropertyLabel(
    item: Record<string, any>,
    cohortsById: Partial<Record<CohortType['id'], CohortType>>,
    keyMapping: KeyMappingInterface,
    valueFormatter: (value: PropertyFilterValue | undefined) => string | string[] | null = (s) => [String(s)]
): string {
    const { value, key, operator, type } = item
    return type === 'cohort'
        ? cohortsById[value]?.name || `ID ${value}`
        : (keyMapping[type === 'element' ? 'element' : 'event'][key]?.label || key) +
              (isOperatorFlag(operator)
                  ? ` ${allOperatorsMapping[operator]}`
                  : ` ${(allOperatorsMapping[operator || 'exact'] || '?').split(' ')[0]} ${
                        value && value.length === 1 && value[0] === '' ? '(empty string)' : valueFormatter(value) || ''
                    } `)
}

// Format a label that gets returned from the /insights api
export function formatLabel(label: string, action: ActionFilter): string {
    if (action.math === 'dau') {
        label += ` (Unique users) `
    } else if (['sum', 'avg', 'min', 'max', 'median', 'p90', 'p95', 'p99'].includes(action.math || '')) {
        label += ` (${action.math} of ${action.math_property}) `
    }
    if (action.properties?.length) {
        label += ` (${action.properties
            .map(
                (property) =>
                    `${property.key ? `${property.key} ` : ''}${
                        allOperatorsMapping[property.operator || 'exact'].split(' ')[0]
                    } ${property.value}`
            )
            .join(', ')})`
    }
    return label.trim()
}

export function objectsEqual(obj1: any, obj2: any): boolean {
    return equal(obj1, obj2)
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

export function delay(ms: number): Promise<number> {
    return new Promise((resolve) => window.setTimeout(resolve, ms))
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

export const posthogEvents = ['$autocapture', '$pageview', '$identify', '$pageleave']

export function isAndroidOrIOS(): boolean {
    return typeof window !== 'undefined' && /Android|iPhone|iPad|iPod/i.test(window.navigator.userAgent)
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

/** Format number with space as the thousands separator. */
export function humanFriendlyNumber(d: number, precision: number = 2): string {
    return d.toLocaleString('en-US', { maximumFractionDigits: precision })
}

export function humanFriendlyDuration(d: string | number | null | undefined, maxUnits?: number): string {
    // Convert `d` (seconds) to a human-readable duration string.
    // Example: `1d 10hrs 9mins 8s`
    if (d === '' || d === null || d === undefined) {
        return ''
    }
    d = Number(d)
    const days = Math.floor(d / 86400)
    const h = Math.floor((d % 86400) / 3600)
    const m = Math.floor((d % 3600) / 60)
    const s = Math.round((d % 3600) % 60)

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
    return units.slice(0, maxUnits).join(' ')
}

export function humanFriendlyDiff(from: dayjs.Dayjs | string, to: dayjs.Dayjs | string): string {
    const diff = dayjs(to).diff(dayjs(from), 'seconds')
    return humanFriendlyDuration(diff)
}

export function humanFriendlyDetailedTime(
    date: dayjs.Dayjs | string | null,
    formatDate = 'MMMM DD, YYYY',
    formatTime = 'h:mm:ss A'
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
        formatString = `[Today] ${formatTime}`
    } else if (parsedDate.isSame(yesterday, 'd')) {
        formatString = `[Yesterday] ${formatTime}`
    } else {
        formatString = `${formatDate} ${formatTime}`
    }
    return parsedDate.format(formatString)
}

// Pad numbers with leading zeros
export const zeroPad = (num: number, places: number): string => String(num).padStart(places, '0')

export function colonDelimitedDuration(d: string | number | null | undefined, numUnits: number = 3): string {
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

    if (numUnits >= 5) {
        weeks = Math.floor(s / 604800)
        s -= weeks * 604800
    }
    if (numUnits >= 4) {
        days = Math.floor(s / 86400)
        s -= days * 86400
    }
    if (numUnits >= 3) {
        h = Math.floor(s / 3600)
        s -= h * 3600
    }
    if (numUnits >= 2) {
        m = Math.floor(s / 60)
        s -= m * 60
    }
    s = Math.floor(s)

    const units = [zeroPad(weeks, 2), zeroPad(days, 2), zeroPad(h, 2), zeroPad(m, 2), zeroPad(s, 2)]

    // get the last `numUnits` elements
    return units.slice(0).slice(-Math.min(numUnits, 5)).join(':')
}

export function colonDelimitedDiff(from: dayjs.Dayjs | string, to: dayjs.Dayjs | string, maxUnits?: number): string {
    const diff = dayjs(to).diff(dayjs(from), 'seconds')
    return colonDelimitedDuration(diff, maxUnits)
}

export function stripHTTP(url: string): string {
    url = url.replace(/(^[0-9]+_)/, '')
    url = url.replace(/(^\w+:|^)\/\//, '')
    return url
}

export function isURL(input: any): boolean {
    if (!input || typeof input !== 'string') {
        return false
    }
    // Regex by regextester.com/115236
    const regexp = /^(?:http(s)?:\/\/)([\w*.-])+(?:[\w*\.-]+)+([\w\-\._~:/?#[\]@%!\$&'\(\)\*\+,;=.])+$/
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
        /^[a-zA-Z0-9.!#$%&'*+\/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/
    return !!string.match?.(regexp)
}

export function eventToDescription(
    event: Pick<EventType, 'elements' | 'event' | 'properties' | 'person'>,
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

export function autoCaptureEventToDescription(
    event: Pick<EventType, 'elements' | 'event' | 'properties'>,
    shortForm: boolean = false
): string {
    if (event.event !== '$autocapture') {
        return event.event
    }

    const getVerb = (): string => {
        if (event.properties.$event_type === 'click') {
            return 'clicked'
        }
        if (event.properties.$event_type === 'change') {
            return 'typed something into'
        }
        if (event.properties.$event_type === 'submit') {
            return 'submitted'
        }
        return 'interacted with'
    }

    const getTag = (): string => {
        if (event.elements?.[0]?.tag_name === 'a') {
            return 'link'
        } else if (event.elements?.[0]?.tag_name === 'img') {
            return 'image'
        }
        return event.elements?.[0]?.tag_name ?? 'element'
    }

    const getValue = (): string | null => {
        if (event.elements?.[0]?.text) {
            return `${shortForm ? '' : 'with text '}"${event.elements[0].text}"`
        } else if (event.elements?.[0]?.attributes?.['attr__aria-label']) {
            return `${shortForm ? '' : 'with aria label '}"${event.elements[0].attributes['attr__aria-label']}"`
        }
        return null
    }

    if (shortForm) {
        return [getVerb(), getValue() ?? getTag()].filter((x) => x).join(' ')
    } else {
        const value = getValue()
        return [getVerb(), getTag(), value].filter((x) => x).join(' ')
    }
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
    } else {
        return 'minute'
    }
}

const DATE_FORMAT = 'MMMM D, YYYY'
const DATE_FORMAT_WITHOUT_YEAR = 'MMMM D'

export const formatDateRange = (dateFrom: dayjs.Dayjs, dateTo: dayjs.Dayjs, format?: string): string => {
    let formatFrom = format ?? DATE_FORMAT
    const formatTo = format ?? DATE_FORMAT
    if ((!format || format === DATE_FORMAT) && dateFrom.year() === dateTo.year()) {
        formatFrom = DATE_FORMAT_WITHOUT_YEAR
    }
    return `${dateFrom.format(formatFrom)} - ${dateTo.format(formatTo)}`
}

export const dateMapping: dateMappingOption[] = [
    { key: 'Custom', values: [] },
    {
        key: 'Today',
        values: ['dStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.startOf('d').format(DATE_FORMAT),
        defaultInterval: 'hour',
    },
    {
        key: 'Yesterday',
        values: ['-1d'],
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
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('m'), date.endOf('d')),
        inactive: true,
        defaultInterval: 'day',
    },
    {
        key: 'Previous month',
        values: ['-1mStart', '-1mEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string =>
            formatDateRange(date.subtract(1, 'm').startOf('M'), date.subtract(1, 'm').endOf('M')),
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
    q: 'quarter',
    m: 'month',
    w: 'week',
    d: 'day',
}

export function dateFilterToText(
    dateFrom: string | dayjs.Dayjs | null | undefined,
    dateTo: string | dayjs.Dayjs | null | undefined,
    defaultValue: string,
    dateOptions: dateMappingOption[] = dateMapping,
    isDateFormatted: boolean = false,
    dateFormat: string = DATE_FORMAT
): string {
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
            return isDateFormatted ? `${dateFrom} - Today` : formatDateRange(dayjs(dateFrom), dayjs())
        } else if (days > 0) {
            return isDateFormatted ? formatDateRange(dayjs(dateFrom), dayjs()) : `Last ${days} days`
        } else if (days === 0) {
            return isDateFormatted ? dayjs(dateFrom).format(dateFormat) : `Today`
        } else {
            return isDateFormatted ? `${dayjs(dateFrom).format(dateFormat)} - ` : `Starting from ${dateFrom}`
        }
    }

    for (const { key, values, getFormattedDate } of dateOptions) {
        if (values[0] === dateFrom && values[1] === dateTo && key !== 'Custom') {
            return isDateFormatted && getFormattedDate ? getFormattedDate(dayjs(), dateFormat) : key
        }
    }

    if (dateFrom) {
        const dateOption = dateOptionsMap[dateFrom.slice(-1)]
        const counter = parseInt(dateFrom.slice(1, -1))
        if (dateOption && counter) {
            let date = null
            switch (dateOption) {
                case 'quarter':
                    date = dayjs().subtract(counter * 3, 'M')
                    break
                case 'months':
                    date = dayjs().subtract(counter, 'M')
                    break
                case 'weeks':
                    date = dayjs().subtract(counter * 7, 'd')
                    break
                default:
                    date = dayjs().subtract(counter, 'd')
                    break
            }
            if (isDateFormatted) {
                return formatDateRange(date, dayjs().endOf('d'))
            } else {
                return `Last ${counter} ${dateOption}${counter > 1 ? 's' : ''}`
            }
        }
    }

    return defaultValue
}

export function copyToClipboard(value: string, description: string = 'text'): boolean {
    if (!navigator.clipboard) {
        lemonToast.warning('Oops! Clipboard capabilities are only available over HTTPS or on localhost')
        return false
    }

    try {
        navigator.clipboard.writeText(value)
        lemonToast.info(`Copied ${description} to clipboard`, {
            icon: <IconCopy />,
        })
        return true
    } catch (e) {
        lemonToast.error(`Could not copy ${description} to clipboard: ${e}`)
        return false
    }
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
    return items[Math.floor(Math.random() * items.length)]
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
    const match = url.match(/^https?:\/\/(?:www\.)?github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)\/?$/)
    if (!match) {
        throw new Error('Must be in the format: https://github.com/user/repo')
    }
    const [, user, repo] = match
    return { user, repo }
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

export function colorForString(s: string): string {
    /*
    Returns a color name for a given string, where the color will always be the same for the same string.
    */
    return tagColors[hashCodeForString(s) % tagColors.length]
}

export function midEllipsis(input: string, maxLength: number): string {
    /* Truncates a string (`input`) in the middle. `maxLength` represents the desired maximum length of the output string
     excluding the ... */
    if (input.length <= maxLength) {
        return input
    }

    const middle = Math.ceil(input.length / 2)
    const excess = Math.ceil((input.length - maxLength) / 2)
    return `${input.substring(0, middle - excess)}...${input.substring(middle + excess)}`
}

export const disableHourFor: Record<string, boolean> = {
    dStart: false,
    '-1d': false,
    '-7d': false,
    '-14d': false,
    '-30d': false,
    '-90d': true,
    mStart: false,
    '-1mStart': false,
    yStart: true,
    all: true,
    other: false,
}

export function autocorrectInterval(filters: Partial<FilterType>): IntervalType {
    if (!filters.interval) {
        return 'day'
    } // undefined/uninitialized

    // @ts-expect-error - Old legacy interval support
    const minute_disabled = filters.interval === 'minute'
    const hour_disabled = disableHourFor[filters.date_from || 'other'] && filters.interval === 'hour'

    if (minute_disabled) {
        return 'hour'
    } else if (hour_disabled) {
        return 'day'
    } else {
        return filters.interval
    }
}

export function pluralize(count: number, singular: string, plural?: string, includeNumber: boolean = true): string {
    if (!plural) {
        plural = singular + 's'
    }
    const form = count === 1 ? singular : plural
    return includeNumber ? `${humanFriendlyNumber(count)} ${form}` : form
}

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
    return value.toString() + ['', 'K', 'M', 'B', 'T', 'P', 'E', 'Z', 'Y'][magnitude]
}

export function roundToDecimal(value: number | null, places: number = 2): string {
    if (value === null) {
        return '-'
    }
    return (Math.round(value * 100) / 100).toFixed(places)
}

export function sortedKeys(object: Record<string, any>): Record<string, any> {
    const newObject: Record<string, any> = {}
    for (const key of Object.keys(object).sort()) {
        newObject[key] = object[key]
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

export function shortTimeZone(timeZone?: string | null, atDate?: Date): string | null {
    /**
     * Return the short timezone identifier for a specific timezone (e.g. BST, EST, PDT, UTC+2).
     * @param timeZone E.g. 'America/New_York'
     * @param atDate
     */
    if (!timeZone) {
        return null
    }
    const date = atDate ? new Date(atDate) : new Date()
    const localeTimeString = date.toLocaleTimeString('en-us', { timeZoneName: 'short', timeZone }).replace('GMT', 'UTC')
    return localeTimeString.split(' ')[2]
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

export function resolveWebhookService(webhookUrl: string): string {
    for (const [service, domain] of Object.entries(WEBHOOK_SERVICES)) {
        if (webhookUrl.includes(domain + '/')) {
            return service
        }
    }
    return 'your webhook service'
}

function hexToRGB(hex: string): { r: number; g: number; b: number } {
    const originalString = hex.trim()
    const hasPoundSign = originalString[0] === '#'
    const originalColor = hasPoundSign ? originalString.slice(1) : originalString

    if (originalColor.length !== 6) {
        console.warn(`Incorrectly formatted color string: ${hex}.`)
        return { r: 0, g: 0, b: 0 }
    }

    const originalBase16 = parseInt(originalColor, 16)
    const r = originalBase16 >> 16
    const g = (originalBase16 >> 8) & 0x00ff
    const b = originalBase16 & 0x0000ff
    return { r, g, b }
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

export function toString(input?: any | null): string {
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
    } catch (error) {
        return false
    }
}

export function validateJsonFormItem(_: any, value: string): Promise<string | void> {
    return validateJson(value) ? Promise.resolve() : Promise.reject('Not valid JSON!')
}

export function ensureStringIsNotBlank(s?: string | null): string | null {
    return typeof s === 'string' && s.trim() !== '' ? s : null
}

export function isMultiSeriesFormula(formula?: string): boolean {
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

export function mapRange(value: number, x1: number, y1: number, x2: number, y2: number): number {
    return Math.floor(((value - x1) * (y2 - x2)) / (y1 - x1) + x2)
}

export function getEventNamesForAction(actionId: string | number, allActions: ActionType[]): string[] {
    const id = parseInt(String(actionId))
    return allActions
        .filter((a) => a.id === id)
        .flatMap((a) => a.steps?.filter((step) => step.event).map((step) => String(step.event)) as string[])
}

export function isPropertyGroup(
    properties: PropertyGroupFilter | PropertyGroupFilterValue | AnyPropertyFilter[] | undefined | AnyPropertyFilter
): properties is PropertyGroupFilter {
    return (
        (properties as PropertyGroupFilter)?.type !== undefined &&
        (properties as PropertyGroupFilter)?.values !== undefined
    )
}

export function flattenPropertyGroup(
    flattenedProperties: AnyPropertyFilter[],
    propertyGroup: PropertyGroupFilter | PropertyGroupFilterValue | AnyPropertyFilter
): AnyPropertyFilter[] {
    const obj: AnyPropertyFilter = {}
    Object.keys(propertyGroup).forEach(function (k) {
        obj[k] = propertyGroup[k]
    })
    if (isValidPropertyFilter(obj)) {
        flattenedProperties.push(obj)
    }
    if (isPropertyGroup(propertyGroup)) {
        return propertyGroup.values.reduce(flattenPropertyGroup, flattenedProperties)
    }
    return flattenedProperties
}

export function convertPropertiesToPropertyGroup(
    properties: PropertyGroupFilter | AnyPropertyFilter[] | undefined
): PropertyGroupFilter {
    if (isPropertyGroup(properties)) {
        return properties
    }
    if (properties && properties.length > 0) {
        return { type: FilterLogicalOperator.And, values: [{ type: FilterLogicalOperator.And, values: properties }] }
    }
    return { type: FilterLogicalOperator.And, values: [] }
}

export function convertPropertyGroupToProperties(
    properties?: PropertyGroupFilter | AnyPropertyFilter[]
): PropertyFilter[] | undefined {
    if (isPropertyGroup(properties)) {
        return flattenPropertyGroup([], properties).filter(isValidPropertyFilter)
    }
    if (properties) {
        return properties.filter(isValidPropertyFilter)
    }
    return properties
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

export function processCohort(cohort: CohortType): CohortType {
    return {
        ...cohort,
        ...{
            /* Populate value_property with value and overwrite value with corresponding behavioral filter type */
            filters: {
                properties: {
                    ...cohort.filters.properties,
                    values: (cohort.filters.properties?.values?.map((group) =>
                        'values' in group
                            ? {
                                  ...group,
                                  values: (group.values as AnyCohortCriteriaType[]).map((c) =>
                                      c.type &&
                                      [BehavioralFilterKey.Cohort, BehavioralFilterKey.Person].includes(c.type) &&
                                      !('value_property' in c)
                                          ? {
                                                ...c,
                                                value_property: c.value,
                                                value:
                                                    c.type === BehavioralFilterKey.Cohort
                                                        ? BehavioralCohortType.InCohort
                                                        : BehavioralEventType.HaveProperty,
                                            }
                                          : c
                                  ),
                              }
                            : group
                    ) ?? []) as CohortCriteriaGroupFilter[] | AnyCohortCriteriaType[],
                },
            },
        },
    }
}
