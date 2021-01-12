import React, { CSSProperties, PropsWithChildren } from 'react'
import api from './api'
import { toast } from 'react-toastify'
import { Spin } from 'antd'
import moment from 'moment'
import { EventType } from '~/types'
import { lightColors } from 'lib/colors'

const SI_PREFIXES: { value: number; symbol: string }[] = [
    { value: 1e18, symbol: 'E' },
    { value: 1e15, symbol: 'P' },
    { value: 1e12, symbol: 'T' },
    { value: 1e9, symbol: 'G' },
    { value: 1e6, symbol: 'M' },
    { value: 1e3, symbol: 'k' },
    { value: 1, symbol: '' },
]
const TRAILING_ZERO_REGEX = /\.0+$|(\.[0-9]*[1-9])0+$/

export function uuid(): string {
    return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, (c) =>
        (parseInt(c) ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (parseInt(c) / 4)))).toString(16)
    )
}

export function toParams(obj: Record<string, any>): string {
    function handleVal(val: any): string {
        if (val._isAMomentObject) {
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

export function fromParams(): Record<string, any> {
    return !window.location.search
        ? {}
        : window.location.search
              .slice(1)
              .split('&')
              .reduce((paramsObject, paramString) => {
                  const [key, value] = paramString.split('=')
                  paramsObject[key] = decodeURIComponent(value)
                  return paramsObject
              }, {} as Record<string, any>)
}

export const colors = ['success', 'secondary', 'warning', 'primary', 'danger', 'info', 'dark', 'light']

export function percentage(division: number): string {
    return division
        ? division.toLocaleString(undefined, {
              style: 'percent',
              maximumFractionDigits: 2,
          })
        : ''
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
            name: string
            id: number
        }
        className: string
        style: CSSProperties
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

export function isOperatorFlag(operator: string): boolean {
    // these filter operators can only be just set, no additional parameter
    return ['is_set', 'is_not_set'].includes(operator)
}

export function formatPropertyLabel(
    item: Record<string, any>,
    cohorts: Record<string, any>[],
    keyMapping: Record<string, Record<string, any>>
): string {
    const { value, key, operator, type } = item
    return type === 'cohort'
        ? cohorts?.find((cohort) => cohort.id === value)?.name || value
        : (keyMapping[type === 'element' ? 'element' : 'event'][key]?.label || key) +
              (isOperatorFlag(operator)
                  ? ` ${operatorMap[operator]}`
                  : ` ${(operatorMap[operator || 'exact'] || '?').split(' ')[0]} ${value || ''}`)
}

export function formatProperty(property: Record<string, any>): string {
    return property.key + ` ${operatorMap[property.operator || 'exact'].split(' ')[0]} ` + property.value
}

// Format a label that gets returned from the /insights api
export function formatLabel(
    label: string,
    action: {
        math: string
        math_property?: string
        properties?: { operator: string; value: any }[]
    }
): string {
    if (action.math === 'dau') {
        label += ` (${action.math.toUpperCase()}) `
    } else if (['sum', 'avg', 'min', 'max', 'median', 'p90', 'p95', 'p99'].includes(action.math)) {
        label += ` (${action.math} of ${action.math_property}) `
    } else {
        label += ' (Total) '
    }
    if (action?.properties?.length) {
        label += ` (${action.properties
            .map((property) => operatorMap[property.operator || 'exact'].split(' ')[0] + ' ' + property.value)
            .join(', ')})`
    }
    return label
}

export function deletePersonData(person: Record<string, any>, callback: () => void): void {
    // DEPRECATED: Remove after releasing PersonsV2 (persons-2353)
    if (window.confirm('Are you sure you want to delete this user? This cannot be undone')) {
        api.delete('api/person/' + person.id).then(() => {
            toast('Person succesfully deleted.')
            if (callback) {
                callback()
            }
        })
    }
}

export function savePersonData(person: Record<string, any>): void {
    // DEPRECATED: Remove after releasing PersonsV2 (persons-2353)
    api.update('api/person/' + person.id, person).then(() => {
        toast('Person Updated')
    })
}

export function objectsEqual(obj1: any, obj2: any): boolean {
    return JSON.stringify(obj1) === JSON.stringify(obj2)
}

export function idToKey(array: Record<string, any>[], keyField: string = 'id'): any {
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
    for (const delay of [10, 100, 500, 750, 1000, 2000]) {
        window.setTimeout(triggerResize, delay)
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

export function humanFriendlyDuration(d: string | number): string {
    d = Number(d)
    const days = Math.floor(d / 86400)
    const h = Math.floor((d % 86400) / 3600)
    const m = Math.floor((d % 3600) / 60)
    const s = Math.floor((d % 3600) % 60)

    const dayDisplay = days > 0 ? days + 'd ' : ''
    const hDisplay = h > 0 ? h + (h == 1 ? 'hr ' : 'hrs ') : ''
    const mDisplay = m > 0 ? m + (m == 1 ? 'min ' : 'mins ') : ''
    const sDisplay = s > 0 ? s + 's' : hDisplay || mDisplay ? '' : '0s'
    return days > 0 ? dayDisplay + hDisplay : hDisplay + mDisplay + sDisplay
}

export function humanFriendlyDiff(from: moment.MomentInput, to: moment.MomentInput): string {
    const diff = moment(to).diff(moment(from), 'seconds')
    return humanFriendlyDuration(diff)
}

export function humanFriendlyDetailedTime(date: moment.MomentInput | null, withSeconds: boolean = false): string {
    if (!date) {
        return 'Never'
    }
    let formatString = 'MMMM Do YYYY h:mm'
    const today = moment().startOf('day')
    const yesterday = today.clone().subtract(1, 'days').startOf('day')
    if (moment(date).isSame(moment(), 'm')) {
        return 'Just now'
    }
    if (moment(date).isSame(today, 'd')) {
        formatString = '[Today] h:mm'
    } else if (moment(date).isSame(yesterday, 'd')) {
        formatString = '[Yesterday] h:mm'
    }
    if (withSeconds) {
        formatString += ':ss a'
    } else {
        formatString += ' a'
    }
    return moment(date).format(formatString)
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
        }
    }
    return name
}

export function determineDifferenceType(
    firstDate: moment.MomentInput,
    secondDate: moment.MomentInput
): 'year' | 'month' | 'week' | 'day' | 'hour' | 'minute' | 'second' {
    const first = moment(firstDate)
    const second = moment(secondDate)
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

export const dateMapping: Record<string, string[]> = {
    Today: ['dStart'],
    Yesterday: ['-1d', 'dStart'],
    'Last 24 hours': ['-24h'],
    'Last 48 hours': ['-48h'],
    'Last 7 days': ['-7d'],
    'Last 14 days': ['-14d'],
    'Last 30 days': ['-30d'],
    'Last 90 days': ['-90d'],
    'This month': ['mStart'],
    'Previous month': ['-1mStart', '-1mEnd'],
    'Year to date': ['yStart'],
    'All time': ['all'],
}

export const isDate = /([0-9]{4}-[0-9]{2}-[0-9]{2})/

export function dateFilterToText(dateFrom: string | moment.Moment, dateTo: string | moment.Moment): string {
    if (moment.isMoment(dateFrom) && moment.isMoment(dateTo)) {
        return `${dateFrom.format('YYYY-MM-DD')} - ${dateTo.format('YYYY-MM-DD')}`
    }
    dateFrom = dateFrom as string
    dateTo = dateTo as string
    if (isDate.test(dateFrom) && isDate.test(dateTo)) {
        return `${dateFrom} - ${dateTo}`
    }
    if (dateFrom === 'dStart') {
        return 'Today'
    } // Changed to "last 24 hours" but this is backwards compatibility
    let name = 'Last 7 days'
    Object.entries(dateMapping).map(([key, value]) => {
        if (value[0] === dateFrom && value[1] === dateTo) {
            name = key
        }
    })[0]
    return name
}

export function humanizeNumber(number: number, digits: number = 1): string {
    if (number === null) {
        return '-'
    }
    // adapted from https://stackoverflow.com/a/9462382/624476
    let matchingPrefix = SI_PREFIXES[SI_PREFIXES.length - 1]
    for (const currentPrefix of SI_PREFIXES) {
        if (number >= currentPrefix.value) {
            matchingPrefix = currentPrefix
            break
        }
    }
    return (number / matchingPrefix.value).toFixed(digits).replace(TRAILING_ZERO_REGEX, '$1') + matchingPrefix.symbol
}

export function copyToClipboard(value: string, description?: string): boolean {
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

export function sampleSingle<T>(items: T[]): T[] {
    if (!items.length) {
        throw Error('Items array is empty!')
    }
    return [items[Math.floor(Math.random() * items.length)]]
}

/** Convert camelCase, PascalCase or snake_case to Title Case. */
export function identifierToHuman(identifier: string | number): string {
    const words: string[] = []
    let currentWord: string = ''
    for (const character of String(identifier).trim()) {
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
    }
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
    return lightColors[hashCodeForString(s) % lightColors.length]
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
