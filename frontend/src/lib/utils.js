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
    division ? division.toLocaleString(undefined, {
        style: 'percent',
        maximumFractionDigits: 2,
    }) : ''

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

export let JSSnippet = props => {
    let url = window.location.origin
    return (
        <pre className="code scrolling-code">
            {`<script>`}
            <br />
            {`  !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="capture identify alias people.set people.set_once set_config register register_once unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);`}
            <br />
            {`  posthog.init('${props.user.team.api_token}', {api_host: '${url}'})`}
            <br />
            {`</script>`}
            <br />
        </pre>
    )
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

export const groupActions = actions => {
    let data = [
        { label: 'Autocapture', options: [] },
        { label: 'Event', options: [] },
        { label: 'Pageview', options: [] },
    ]
    actions.map(action => {
        let format = { label: action.name, value: action.id }
        if (actionContains(action, '$autocapture')) data[0].options.push(format)
        if (actionContains(action, '$pageview')) data[2].options.push(format)
        if (!actionContains(action, '$autocapture') && !actionContains(action, '$pageview'))
            data[1].options.push(format)
    })
    return data
}

export const actionContains = (action, event) => {
    return action.steps.filter(step => step.event == event).length > 0
}

export const groupEvents = events => {
    let data = [{ label: 'All Events', options: [] }]

    events.map(event => {
        let format = { label: event.name, value: event.name }
        data[0].options.push(format)
    })
    return data
}

export const capitalizeFirstLetter = (string) => {
    return string.charAt(0).toUpperCase() + string.slice(1);
}