import React, { Component } from 'react'
import api from './Api';
import { toast } from 'react-toastify';
import PropTypes from 'prop-types';

export function uuid() {
    return ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
      (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
    );
  }


export let toParams = (obj) => Object.entries(obj).filter(([key, val]) => val).map(([key, val]) => `${key}=${encodeURIComponent(val)}`).join('&')
export let fromParams = () => window.location.search != '' ? window.location.search.slice(1).split('&').reduce((a, b) => { b = b.split('='); a[b[0]] = decodeURIComponent(b[1]); return a; }, {}) : {};

export let colors = ['success', 'secondary', 'warning', 'primary', 'danger', 'info', 'dark', 'light']
export let percentage = (division) => division.toLocaleString(undefined, {style: 'percent', maximumFractionDigits: 2})

export let Loading = () => <div className='loading-overlay'><div></div></div>;

export function Card(props) {
    return <div {...props} className={'card ' + props.className} style={props.style} title=''>
        {props.title && <div className='card-header'>
            {props.title}
        </div>}
            {props.children}
    </div>
}

export let DeleteWithUndo = (props) => {
    let deleteWithUndo = (undo) => {
        api.update('api/' + props.endpoint + '/' + props.object.id, {...props.object, deleted: (undo ? false : true)}).then(() => {
            props.callback();
            let response = <div>
                {
                    !undo ? <span>"<strong>{props.object.name}</strong>" deleted. <a href='#' onClick={(e) => { e.preventDefault(); deleteWithUndo(true) }}>Click here to undo</a></span> : 
                    <span>Delete un-done</span>
                }
            </div>
            toast(response, {toastId: "delete-item-" + props.object.id})
        })
    }

    return <a
        href='#'
        onClick={(e) => {
            e.preventDefault();
            deleteWithUndo()
        }}
        className={props.className}
        style={props.style}>{props.children}</a>
}
DeleteWithUndo.propTypes = {
    endpoint: PropTypes.string.isRequired,
    object: PropTypes.shape({name: PropTypes.string.isRequired, id: PropTypes.number.isRequired}).isRequired,
    className: PropTypes.string,
    style: PropTypes.object
}

export class Dropdown extends Component {
    constructor(props) {
        super(props)
    
        this.state = {}
        this.close = this.close.bind(this);
        this.open = this.open.bind(this);
    }
    close() {
        this.setState({menuOpen: false})
        document.removeEventListener('click', this.close)
    }
    open() {
        this.setState({menuOpen: true});
        document.addEventListener('click', this.close)
    }
    componentWillUnmount() {
        document.removeEventListener('click', this.close)
    }
    render() {
      return <div className={"dropdown " + this.props.className} style={{display: 'inline', marginTop: -6}}>
            <a className='cursor-pointer' style={{fontSize: '2rem', color: 'var(--gray)', lineHeight: '1rem', ...this.props.style}} onClick={this.open}>
                {this.props.action}
                &hellip;
            </a>
            <div className={"dropdown-menu " + (this.state.menuOpen && 'show')} aria-labelledby="dropdownMenuButton">
                {this.props.children}
            </div>
        </div>
    }
}

export let JSSnippet = (props) => {
    let url = window.location.origin == 'https://app.posthog.com' ? 'https://t.posthog.com' : window.location.origin
    return <pre className='code'>
        {`<script src="${url}/static/array.js"></script>`}<br />
        {`<script>`}<br />
        {`posthog.init('${props.user.team.api_token}', {api_host: '${url}'})`}<br />
        {`</script>`}<br />
    </pre>
}