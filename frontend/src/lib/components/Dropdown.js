import React, { Component } from 'react'

export class Dropdown extends Component {
    constructor(props) {
        super(props)
        this.state = {}
        this.close = this.close.bind(this)
        this.open = this.open.bind(this)
    }
    close(e) {
        if (
            e.target.closest('.dropdown-no-close') ||
            e.target.closest('.react-datepicker')
        )
            return
        this.setState({ menuOpen: false })
        document.removeEventListener('click', this.close)
    }
    open() {
        this.setState({ menuOpen: true })
        document.addEventListener('click', this.close)
    }
    componentWillUnmount() {
        document.removeEventListener('click', this.close)
    }
    render() {
        return (
            <div
                className={'dropdown ' + this.props.className}
                style={{
                    display: 'inline',
                    marginTop: -6,
                    ...this.props.style,
                }}
            >
                <a
                    className={'cursor-pointer ' + this.props.buttonClassName}
                    style={{ ...this.props.buttonStyle }}
                    onClick={this.open}
                >
                    {this.props.title || <span>&hellip;</span>}
                </a>
                <div
                    className={
                        'dropdown-menu ' + (this.state.menuOpen && 'show')
                    }
                    aria-labelledby="dropdownMenuButton"
                >
                    {this.props.children}
                </div>
            </div>
        )
    }
}
