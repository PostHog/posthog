import React, { CSSProperties, PropsWithChildren } from 'react'
import api from './api'
import { toast } from 'react-toastify'
import { Button, Spin } from 'antd'
import dayjs from 'dayjs'
import { EventType, FilterType, ActionFilter, IntervalType, ItemMode, DashboardMode } from '~/types'
import { tagColors } from 'lib/colors'
import { CustomerServiceOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { featureFlagLogic } from './logic/featureFlagLogic'
import { open } from '@papercups-io/chat-widget'
import posthog from 'posthog-js'
import { FEATURE_FLAGS, WEBHOOK_SERVICES } from 'lib/constants'
import { KeyMappingInterface } from 'lib/components/PropertyKeyInfo'
import { AlignType } from 'rc-trigger/lib/interface'
import { DashboardEventSource } from './utils/eventUsageLogic'

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
        (parseInt(c) ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (parseInt(c) / 4)))).toString(16)
    )
}

export function areObjectValuesEmpty(obj: Record<string, any>): boolean {
    return (
        !!obj && typeof obj === 'object' && !Object.values(obj).some((x) => x !== null && x !== '' && x !== undefined)
    )
}

export function toParams(obj: Record<string, any>): string {
    function handleVal(val: any): string {
        if (dayjs.isDayjs(val)) {
            return encodeURIComponent(val.format('YYYY-MM-DD'))
        }
        val = typeof val === 'object' ? JSON.stringify(val) : val
        return encodeURIComponent(val)
    }
    return Object.entries(obj)
        .filter((item) => item[1] != undefined && item[1] != null)
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

export function percentage(division: number): string {
    return division
        ? division.toLocaleString(undefined, {
              style: 'percent',
              maximumFractionDigits: 2,
          })
        : ''
}

export function editingToast(
    item: string,
    setItemMode:
        | ((mode: DashboardMode | null, source: DashboardEventSource) => void)
        | ((mode: ItemMode | null, source: DashboardEventSource) => void)
): any {
    return toast(
        <>
            <h1>{item} edit mode</h1>
            <p>Tap below when finished.</p>
            <div className="text-right">
                <Button>Finish editing</Button>
            </div>
        </>,
        {
            type: 'info',
            autoClose: false,
            onClick: () => setItemMode(null, DashboardEventSource.Toast),
            closeButton: false,
            className: 'drag-items-toast accent-border',
        }
    )
}

export function errorToast(title?: string, message?: string, errorDetail?: string, errorCode?: string): void {
    /**
     * Shows a standardized error toast when something goes wrong. Automated for any loader usage.
     * @param title Title message of the toast
     * @param message Body message on the toast
     * @param errorDetail Error response returned from the server, or any other more specific error detail.
     * @param errorCode Error code from the server that can help track the error.
     */

    const handleHelp = (): void => {
        const papercupsOn = featureFlagLogic.values.featureFlags[FEATURE_FLAGS.PAPERCUPS_ENABLED]
        if (papercupsOn) {
            open()
        } else {
            window.open('https://posthog.com/support?utm_medium=in-product&utm_campaign=error-toast')
        }
        posthog.capture('error toast help requested', { papercups_enabled: papercupsOn }) // Can't use eventUsageLogic here, not mounted
    }

    toast.dismiss('error') // This will ensure only the last error is shown

    setTimeout(
        () =>
            toast.error(
                <div>
                    <h1>
                        <ExclamationCircleOutlined /> {title || 'Something went wrong'}
                    </h1>
                    <p>
                        {message || 'We could not complete your action. Detailed error:'}{' '}
                        <span className="error-details">{errorDetail || 'Unknown exception.'}</span>
                    </p>
                    <p className="mt-05">
                        Please <b>try again or contact us</b> if the error persists.
                    </p>
                    <div className="action-bar">
                        {errorCode && <span>Code: {errorCode}</span>}
                        <span className="help-button">
                            <Button type="link" onClick={handleHelp}>
                                <CustomerServiceOutlined /> Need help?
                            </Button>
                        </span>
                    </div>
                </div>,
                {
                    toastId: 'error', // will ensure only one error is displayed at a time
                }
            ),
        100
    )
}

export function Loading(props: Record<string, any>): JSX.Element {
    return (
        <div className="loading-overlay" style={props.style}>
            <Spin />
        </div>
    )
}

export function TableRowLoading({
    colSpan = 1,
    asOverlay = false,
}: {
    colSpan: number
    asOverlay: boolean
}): JSX.Element {
    return (
        <tr className={asOverlay ? 'loading-overlay over-table' : ''}>
            <td colSpan={colSpan} style={{ padding: 50, textAlign: 'center' }}>
                <Spin />
            </td>
        </tr>
    )
}

export function SceneLoading(): JSX.Element {
    return (
        <div style={{ textAlign: 'center', marginTop: '20vh' }}>
            <Spin />
        </div>
    )
}

export function deleteWithUndo({ undo = false, ...props }: Record<string, any>): void {
    api.update(`api/${props.endpoint}/${props.object.id}`, {
        ...props.object,
        deleted: !undo,
    }).then(() => {
        props.callback?.()
        const response = (
            <span>
                <b>{props.object.name ?? 'Untitled'}</b>
                {!undo ? ' deleted. Click to undo.' : ' deletion undone.'}
            </span>
        )
        toast(response, {
            toastId: `delete-item-${props.object.id}-${undo}`,
            onClick: () => {
                deleteWithUndo({ undo: true, ...props })
            },
        })
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

export const operatorMap: Record<string, string> = {
    exact: '= equals',
    is_not: "≠ doesn't equal",
    icontains: '∋ contains',
    not_icontains: "∌ doesn't contain",
    regex: '∼ matches regex',
    not_regex: "≁ doesn't match regex",
    gt: '> greater than',
    lt: '< lower than',
    is_set: '✓ is set',
    is_not_set: '✕ is not set',
}

export function isOperatorMulti(operator: string): boolean {
    return ['exact', 'is_not'].includes(operator)
}

export function isOperatorFlag(operator: string): boolean {
    // these filter operators can only be just set, no additional parameter
    return ['is_set', 'is_not_set'].includes(operator)
}

export function isOperatorRegex(operator: string): boolean {
    return ['regex', 'not_regex'].includes(operator)
}

export function formatPropertyLabel(
    item: Record<string, any>,
    cohorts: Record<string, any>[],
    keyMapping: KeyMappingInterface
): string {
    const { value, key, operator, type } = item
    return type === 'cohort'
        ? cohorts?.find((cohort) => cohort.id === value)?.name || value
        : (keyMapping[type === 'element' ? 'element' : 'event'][key]?.label || key) +
              (isOperatorFlag(operator)
                  ? ` ${operatorMap[operator]}`
                  : ` ${(operatorMap[operator || 'exact'] || '?').split(' ')[0]} ${
                        value && value.length === 1 && value[0] === '' ? '(empty string)' : value || ''
                    } `)
}

export function formatProperty(property: Record<string, any>): string {
    return property.key + ` ${operatorMap[property.operator || 'exact'].split(' ')[0]} ` + property.value
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
                        operatorMap[property.operator || 'exact'].split(' ')[0]
                    } ${property.value}`
            )
            .join(', ')})`
    }
    return label
}

export function objectsEqual(obj1: any, obj2: any): boolean {
    return JSON.stringify(obj1) === JSON.stringify(obj2)
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

/**
 * Trigger a resize event on window.
 */
export function triggerResize(): void {
    try {
        window.dispatchEvent(new Event('resize'))
    } catch (error) {
        // will break on IE11
    }
}

/**
 * Trigger a resize event on window a few times between 10 to 2000 ms after the menu was collapsed/expanded.
 * We need this so the dashboard resizes itself properly, as the available div width will still
 * change when the sidebar's expansion is animating.
 */
export function triggerResizeAfterADelay(): void {
    for (const duration of [10, 100, 500, 750, 1000, 2000]) {
        window.setTimeout(triggerResize, duration)
    }
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
    const mDisplay = m > 0 ? m + 'min' : ''
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

export function humanFriendlyDetailedTime(date: dayjs.Dayjs | string | null, withSeconds: boolean = false): string {
    if (!date) {
        return 'Never'
    }
    const parsedDate = dayjs(date)
    let formatString = 'MMMM Do YYYY h:mm'
    const today = dayjs().startOf('day')
    const yesterday = today.clone().subtract(1, 'days').startOf('day')
    if (parsedDate.isSame(dayjs(), 'm')) {
        return 'Just now'
    }
    if (parsedDate.isSame(today, 'd')) {
        formatString = '[Today] h:mm'
    } else if (parsedDate.isSame(yesterday, 'd')) {
        formatString = '[Yesterday] h:mm'
    }
    if (withSeconds) {
        formatString += ':ss a'
    } else {
        formatString += ' a'
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
    s = Math.round(s)

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
    // https://stackoverflow.com/questions/3809401/what-is-a-good-regular-expression-to-match-a-url
    const regexp = /^\s*https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)/gi
    return !!input.match?.(regexp)
}

export function isEmail(string: string): boolean {
    if (!string) {
        return false
    }
    // https://html.spec.whatwg.org/multipage/input.html#valid-e-mail-address
    const regexp = /^[a-zA-Z0-9.!#$%&'*+\/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/
    return !!string.match?.(regexp)
}

export function eventToName(event: EventType): string {
    if (event.event !== '$autocapture') {
        return event.event
    }
    let name = ''
    if (event.properties.$event_type === 'click') {
        name += 'clicked '
    }
    if (event.properties.$event_type === 'change') {
        name += 'typed something into '
    }
    if (event.properties.$event_type === 'submit') {
        name += 'submitted '
    }

    if (event.elements.length > 0) {
        if (event.elements[0].tag_name === 'a') {
            name += 'link'
        } else if (event.elements[0].tag_name === 'img') {
            name += 'image'
        } else {
            name += event.elements[0].tag_name
        }
        if (event.elements[0].text) {
            name += ' with text "' + event.elements[0].text + '"'
        } else if (event.elements[0].attributes['attr__aria-label']) {
            name += ' with aria label "' + event.elements[0].attributes['attr__aria-label'] + '"'
        }
    }
    return name
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

interface dateMappingOption {
    inactive?: boolean // Options removed due to low usage (see relevant PR); will not show up for new insights but will be kept for existing
    values: string[]
}

export const dateMapping: Record<string, dateMappingOption> = {
    Custom: { values: [] },
    Today: { values: ['dStart'] },
    Yesterday: { values: ['-1d', 'dStart'] },
    'Last 24 hours': { values: ['-24h'] },
    'Last 48 hours': { values: ['-48h'], inactive: true },
    'Last 7 days': { values: ['-7d'] },
    'Last 14 days': { values: ['-14d'] },
    'Last 30 days': { values: ['-30d'] },
    'Last 90 days': { values: ['-90d'] },
    'This month': { values: ['mStart'], inactive: true },
    'Previous month': { values: ['-1mStart', '-1mEnd'], inactive: true },
    'Year to date': { values: ['yStart'] },
    'All time': { values: ['all'] },
}

export const isDate = /([0-9]{4}-[0-9]{2}-[0-9]{2})/

export function dateFilterToText(
    dateFrom: string | dayjs.Dayjs | null | undefined,
    dateTo: string | dayjs.Dayjs | null | undefined,
    defaultValue: string
): string {
    if (dayjs.isDayjs(dateFrom) && dayjs.isDayjs(dateTo)) {
        return `${dateFrom.format('YYYY-MM-DD')} - ${dateTo.format('YYYY-MM-DD')}`
    }
    dateFrom = (dateFrom || undefined) as string | undefined
    dateTo = (dateTo || undefined) as string | undefined

    if (isDate.test(dateFrom || '') && isDate.test(dateTo || '')) {
        return `${dateFrom} - ${dateTo}`
    }

    if (dateFrom === 'dStart') {
        // Changed to "last 24 hours" but this is backwards compatibility
        return 'Today'
    }

    if (isDate.test(dateFrom || '') && !isDate.test(dateTo || '')) {
        const days = dayjs().diff(dayjs(dateFrom), 'days')
        if (days > 366) {
            return `${dateFrom} - Today`
        } else if (days > 0) {
            return `Last ${days} days`
        } else if (days === 0) {
            return `Today`
        } else {
            return `Starting from ${dateFrom}`
        }
    }

    let name = defaultValue
    Object.entries(dateMapping).map(([key, { values }]) => {
        if (values[0] === dateFrom && values[1] === dateTo && key !== 'Custom') {
            name = key
        }
    })[0]
    return name
}

export function copyToClipboard(value: string, description?: string): boolean {
    if (!navigator.clipboard) {
        toast.info('Oops! Clipboard capabilities are only available over HTTPS or localhost.')
        return false
    }
    const descriptionAdjusted = description
        ? description.charAt(0).toUpperCase() + description.slice(1).trim() + ' '
        : ''
    try {
        navigator.clipboard.writeText(value)
        toast(
            <div>
                <h1 className="text-success">Copied to clipboard!</h1>
                <p>{descriptionAdjusted} has been copied to your clipboard.</p>
            </div>
        )
        return true
    } catch (e) {
        toast.error(`Could not copy ${descriptionAdjusted}to clipboard: ${e}`)
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

/** Convert camelCase, PascalCase or snake_case to Title Case. */
export function identifierToHuman(identifier: string | number): string {
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
    return words.map((word) => word[0].toUpperCase() + word.slice(1)).join(' ')
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

export const disableMinuteFor: Record<string, boolean> = {
    dStart: false,
    '-1d': false,
    '-7d': true,
    '-14d': true,
    '-30d': true,
    '-90d': true,
    mStart: true,
    '-1mStart': true,
    yStart: true,
    all: true,
    other: false,
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

    const minute_disabled = disableMinuteFor[filters.date_from || 'other'] && filters.interval === 'minute'
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
    return includeNumber ? `${count} ${form}` : form
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

export function shortTimeZone(timeZone?: string, atDate: Date = new Date()): string {
    /**
     * Return the short timezone identifier for a specific timezone (e.g. BST, EST, PDT, UTC+2).
     * @param timeZone E.g. 'America/New_York'
     * @param atDate
     */
    const localeTimeString = new Date(atDate).toLocaleTimeString('en-us', { timeZoneName: 'short', timeZone })
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

export function maybeAddCommasToInteger(value: any): any {
    const isNumber = !isNaN(value)
    if (!isNumber) {
        return value
    }
    const internationalNumberFormat = new Intl.NumberFormat('en-US')
    return internationalNumberFormat.format(value)
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

export function validateJsonFormItem(_: any, value: string): Promise<string | void> {
    try {
        JSON.parse(value)
        return Promise.resolve()
    } catch (error) {
        return Promise.reject('Not valid JSON!')
    }
}
