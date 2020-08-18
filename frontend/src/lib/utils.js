import React from 'react'
import api from './api'
import { toast } from 'react-toastify'
import PropTypes from 'prop-types'
import { Spin } from 'antd'
import moment from 'moment'

export function uuid() {
    return ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, (c) =>
        (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)
    )
}

export let toParams = (obj) => {
    let handleVal = (val) => {
        if (val._isAMomentObject) return encodeURIComponent(val.format('YYYY-MM-DD'))
        val = typeof val === 'object' ? JSON.stringify(val) : val
        return encodeURIComponent(val)
    }
    return Object.entries(obj)
        .filter((item) => item[1] != undefined && item[1] != null)
        .map(([key, val]) => `${key}=${handleVal(val)}`)
        .join('&')
}
export let fromParams = () =>
    window.location.search != ''
        ? window.location.search
              .slice(1)
              .split('&')
              .reduce((a, b) => {
                  b = b.split('=')
                  a[b[0]] = decodeURIComponent(b[1])
                  return a
              }, {})
        : {}

export let colors = ['success', 'secondary', 'warning', 'primary', 'danger', 'info', 'dark', 'light']
export let percentage = (division) =>
    division
        ? division.toLocaleString(undefined, {
              style: 'percent',
              maximumFractionDigits: 2,
          })
        : ''

export let Loading = () => (
    <div className="loading-overlay">
        <div></div>
        <Spin />
    </div>
)

export const TableRowLoading = ({ colSpan = 1, asOverlay = false }) => (
    <tr className={asOverlay ? 'loading-overlay over-table' : ''}>
        <td colSpan={colSpan} style={{ padding: 50, textAlign: 'center' }}>
            <Spin />
        </td>
    </tr>
)

export const SceneLoading = () => (
    <div style={{ textAlign: 'center', marginTop: '20vh' }}>
        <Spin />
    </div>
)

export let CloseButton = (props) => {
    return (
        <span {...props} className={'close cursor-pointer ' + props.className} style={{ ...props.style }}>
            <span aria-hidden="true">&times;</span>
        </span>
    )
}

export function Card(props) {
    return (
        <div
            {...props}
            className={'card' + (props.className ? ` ${props.className}` : '')}
            style={props.style}
            title=""
        >
            {props.title && <div className="card-header">{props.title}</div>}
            {props.children}
        </div>
    )
}

export const deleteWithUndo = ({ undo = false, ...props }) => {
    api.update('api/' + props.endpoint + '/' + props.object.id, {
        ...props.object,
        deleted: !undo,
    }).then(() => {
        props.callback?.()
        let response = (
            <div>
                {!undo ? (
                    <span>
                        "<strong>{props.object.name || 'Untitled'}</strong>" deleted.{' '}
                        <a
                            href="#"
                            onClick={(e) => {
                                e.preventDefault()
                                deleteWithUndo({ undo: true, ...props })
                            }}
                        >
                            Click here to undo
                        </a>
                    </span>
                ) : (
                    <span>Delete un-done</span>
                )}
            </div>
        )
        toast(response, { toastId: 'delete-item-' + props.object.id })
    })
}

export const DeleteWithUndo = (props) => {
    const { className, style, children } = props
    return (
        <a
            href="#"
            onClick={(e) => {
                e.preventDefault()
                deleteWithUndo(props)
            }}
            className={className}
            style={style}
        >
            {children}
        </a>
    )
}
DeleteWithUndo.propTypes = {
    endpoint: PropTypes.string.isRequired,
    object: PropTypes.shape({
        name: PropTypes.string.isRequired,
        id: PropTypes.number.isRequired,
    }).isRequired,
    className: PropTypes.string,
    style: PropTypes.object,
}

export let selectStyle = {
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

export let debounce = (func, wait, immediate) => {
    var timeout
    return function () {
        var context = this, // eslint-disable-line
            args = arguments
        var later = function () {
            timeout = null
            if (!immediate) func.apply(context, args)
        }
        var callNow = immediate && !timeout
        clearTimeout(timeout)
        timeout = setTimeout(later, wait)
        if (callNow) func.apply(context, args)
    }
}

export const capitalizeFirstLetter = (string) => {
    return string.charAt(0).toUpperCase() + string.slice(1)
}

export const operatorMap = {
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

export function isOperatorFlag(operator) {
    // these filter operators can only be just set, no additional parameter
    return ['is_set', 'is_not_set'].includes(operator)
}

export const formatProperty = (property) => {
    return property.key + ` ${operatorMap[property.operator || 'exact'].split(' ')[0]} ` + property.value
}

export const deletePersonData = (person, callback) => {
    window.confirm('Are you sure you want to delete this user? This cannot be undone') &&
        api.delete('api/person/' + person.id).then(() => {
            toast('Person succesfully deleted.')
            if (callback) callback()
        })
}

export const objectsEqual = (obj1, obj2) => JSON.stringify(obj1) === JSON.stringify(obj2)

export const idToKey = (array, keyField = 'id') => {
    const object = {}
    for (const element of array) {
        object[element[keyField]] = element
    }
    return object
}

export const delay = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms))

// Trigger a window.reisize event a few times 0...2 sec after the menu was collapsed/expanded
// We need this so the dashboard resizes itself properly, as the available div width will still
// change when the sidebar's expansion is animating.
export const triggerResize = () => {
    try {
        window.dispatchEvent(new Event('resize'))
    } catch (error) {
        // will break on IE11
    }
}
export const triggerResizeAfterADelay = () => {
    for (const delay of [10, 100, 500, 750, 1000, 2000]) {
        window.setTimeout(triggerResize, delay)
    }
}

export function clearDOMTextSelection() {
    if (window.getSelection) {
        if (window.getSelection().empty) {
            // Chrome
            window.getSelection().empty()
        } else if (window.getSelection().removeAllRanges) {
            // Firefox
            window.getSelection().removeAllRanges()
        }
    } else if (document.selection) {
        // IE?
        document.selection.empty()
    }
}

export const posthogEvents = ['$autocapture', '$pageview', '$identify', '$pageleave']

export function isAndroidOrIOS() {
    return typeof window !== 'undefined' && /Android|iPhone|iPad|iPod/i.test(window.navigator.userAgent)
}

export function slugify(text) {
    return text
        .toString() // Cast to string
        .toLowerCase() // Convert the string to lowercase letters
        .normalize('NFD') // The normalize() method returns the Unicode Normalization Form of a given string.
        .trim() // Remove whitespace from both sides of a string
        .replace(/\s+/g, '-') // Replace spaces with -
        .replace(/[^\w-]+/g, '') // Remove all non-word chars
        .replace(/--+/g, '-')
}

export function humanFriendlyDuration(d) {
    d = Number(d)
    var days = Math.floor(d / 86400)
    var h = Math.floor((d % 86400) / 3600)
    var m = Math.floor((d % 3600) / 60)
    var s = Math.floor((d % 3600) % 60)

    var dayDisplay = days > 0 ? days + 'd ' : ''
    var hDisplay = h > 0 ? h + (h == 1 ? 'hr ' : 'hrs ') : ''
    var mDisplay = m > 0 ? m + (m == 1 ? 'min ' : 'mins ') : ''
    var sDisplay = s > 0 ? s + 's' : hDisplay || mDisplay ? '' : '0s'
    return days > 0 ? dayDisplay + hDisplay : hDisplay + mDisplay + sDisplay
}

export function humanFriendlyDiff(from, to) {
    const diff = moment(to).diff(moment(from), 'seconds')
    return humanFriendlyDuration(diff)
}

export function humanFriendlyDetailedTime(date, withSeconds = false) {
    let formatString = 'MMMM Do YYYY h:mm'
    const today = moment().startOf('day')
    const yesterday = today.clone().subtract(1, 'days').startOf('day')
    if (moment(date).isSame(today, 'd')) {
        formatString = '[Today] h:mm'
    } else if (moment(date).isSame(yesterday, 'd')) {
        formatString = '[Yesterday] h:mm'
    }
    if (withSeconds) formatString += ':s a'
    else formatString += ' a'
    return moment(date).format(formatString)
}

export function stripHTTP(url) {
    url = url.replace(/(^[0-9]+_)/, '')
    url = url.replace(/(^\w+:|^)\/\//, '')
    return url
}

export const eventToName = (event) => {
    if (event.event !== '$autocapture') return event.event
    let name = ''
    if (event.properties.$event_type === 'click') name += 'clicked '
    if (event.properties.$event_type === 'change') name += 'typed something into '
    if (event.properties.$event_type === 'submit') name += 'submitted '

    if (event.elements.length > 0) {
        if (event.elements[0].tag_name === 'a') {
            name += 'link'
        } else if (event.elements[0].tag_name === 'img') {
            name += 'image'
        } else {
            name += event.elements[0].tag_name
        }
        if (event.elements[0].text) name += ' with text "' + event.elements[0].text + '"'
    }
    return name
}

export function determineDifferenceType(firstDate, secondDate) {
    const first = moment(firstDate)
    const second = moment(secondDate)
    if (first.diff(second, 'years') !== 0) return 'year'
    else if (first.diff(second, 'months') !== 0) return 'month'
    else if (first.diff(second, 'weeks') !== 0) return 'week'
    else if (first.diff(second, 'days') !== 0) return 'day'
    else if (first.diff(second, 'hours') !== 0) return 'hour'
    else return 'minute'
}

// https://stackoverflow.com/a/9462382/624476
export function humanizeNumber(num, digits = 1) {
    var si = [
        { value: 1, symbol: '' },
        { value: 1e3, symbol: 'k' },
        { value: 1e6, symbol: 'M' },
        { value: 1e9, symbol: 'G' },
        { value: 1e12, symbol: 'T' },
        { value: 1e15, symbol: 'P' },
        { value: 1e18, symbol: 'E' },
    ]
    var rx = /\.0+$|(\.[0-9]*[1-9])0+$/
    var i
    for (i = si.length - 1; i > 0; i--) {
        if (num >= si[i].value) {
            break
        }
    }
    return (num / si[i].value).toFixed(digits).replace(rx, '$1') + si[i].symbol
}
