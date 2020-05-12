import React from 'react'
import api from './api'
import { toast } from 'react-toastify'
import PropTypes from 'prop-types'
import { Spin } from 'antd'

export function uuid() {
    return ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, c =>
        (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)
    )
}

export let toParams = obj => {
    let handleVal = val => {
        if (val._isAMomentObject) return encodeURIComponent(val.format('YYYY-MM-DD'))
        val = typeof val === 'object' ? JSON.stringify(val) : val
        return encodeURIComponent(val)
    }
    return Object.entries(obj)
        .filter(([key, val]) => val)
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
export let percentage = division =>
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

export let CloseButton = props => {
    return (
        <span {...props} className={'close cursor-pointer ' + props.className} style={{ ...props.style }}>
            <span aria-hidden="true">&times;</span>
        </span>
    )
}

export function Card(props) {
    return (
        <div {...props} className={'card ' + props.className} style={props.style} title="">
            {props.title && <div className="card-header">{props.title}</div>}
            {props.children}
        </div>
    )
}

export const deleteWithUndo = ({ undo, ...props }) => {
    api.update('api/' + props.endpoint + '/' + props.object.id, {
        ...props.object,
        deleted: !undo,
    }).then(() => {
        props.callback()
        let response = (
            <div>
                {!undo ? (
                    <span>
                        "<strong>{props.object.name}</strong>" deleted.{' '}
                        <a
                            href="#"
                            onClick={e => {
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

export const DeleteWithUndo = ({ className, style, children }) => {
    return (
        <a
            href="#"
            onClick={e => {
                e.preventDefault()
                deleteWithUndo()
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
    control: base => ({
        ...base,
        height: 31,
        minHeight: 31,
    }),
    indicatorsContainer: base => ({
        ...base,
        height: 31,
    }),
    input: base => ({
        ...base,
        paddingBottom: 0,
        paddingTop: 0,
        margin: 0,
        opacity: 1,
    }),
    valueContainer: base => ({
        ...base,
        padding: '0 8px',
        marginTop: -2,
    }),
    option: base => ({
        ...base,
        padding: '2px 15px',
    }),
}

export let debounce = (func, wait, immediate) => {
    var timeout
    return function() {
        var context = this,
            args = arguments
        var later = function() {
            timeout = null
            if (!immediate) func.apply(context, args)
        }
        var callNow = immediate && !timeout
        clearTimeout(timeout)
        timeout = setTimeout(later, wait)
        if (callNow) func.apply(context, args)
    }
}

export const capitalizeFirstLetter = string => {
    return string.charAt(0).toUpperCase() + string.slice(1)
}

export const operatorMap = {
    exact: '= equals',
    is_not: "≠ doesn't equal",
    icontains: '∋ contains',
    not_icontains: "∌ doesn't contain",
    gt: '> greater than',
    lt: '< lower than',
}

const operatorEntries = Object.entries(operatorMap).reverse()

export const formatFilterName = str => {
    for (let [key, value] of operatorEntries) {
        if (str.includes(key)) return str.replace('__' + key, '') + ` ${value.split(' ')[0]} `
    }
    return str + ` ${operatorMap['exact'].split(' ')[0]} `
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

export const delay = ms => new Promise(resolve => window.setTimeout(resolve, ms))

// Trigger a window.reisize event a few times 0...2 sec after the menu was collapsed/expanded
// We need this so the dashboard resizes itself properly, as the available div width will still
// change when the sidebar's expansion is animating.
export const triggerResize = () => {
    window.dispatchEvent(new Event('resize'))
}
export const triggerResizeAfterADelay = () => {
    for (const delay of [10, 100, 500, 750, 1000, 2000]) {
        window.setTimeout(triggerResize, delay)
    }
}
