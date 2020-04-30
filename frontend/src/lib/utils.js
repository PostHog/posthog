import React from 'react'
import api from './api'
import { toast } from 'react-toastify'
import PropTypes from 'prop-types'

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

export let DeleteWithUndo = props => {
    let deleteWithUndo = undo => {
        api.update('api/' + props.endpoint + '/' + props.object.id, {
            ...props.object,
            deleted: undo ? false : true,
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
                                    deleteWithUndo(true)
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

    return (
        <a
            href="#"
            onClick={e => {
                e.preventDefault()
                deleteWithUndo()
            }}
            className={props.className}
            style={props.style}
        >
            {props.children}
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
    null: '= equals',
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
    return str + ` ${operatorMap['null'].split(' ')[0]} `
}
