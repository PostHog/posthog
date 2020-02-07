import React, { Component } from 'react'

export function uuid() {
    return ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
      (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
    );
  }


export let toParams = (obj) => Object.entries(obj).filter(([key, val]) => val).map(([key, val]) => `${key}=${encodeURIComponent(val)}`).join('&')
export let fromParams = () => window.location.search != '' ? window.location.search.slice(1).split('&').reduce((a, b) => { b = b.split('='); a[b[0]] = decodeURIComponent(b[1]); return a; }, {}) : {};

export let colors = ['success', 'secondary', 'warning', 'primary', 'danger', 'info', 'dark', 'light']
export let percentage = (division) => division.toLocaleString(undefined, {style: 'percent', maximumFractionDigits: 2})

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