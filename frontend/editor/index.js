import React, { Component } from "react";
import ReactDOM from "react-dom";
import api from '../src/api';
import Simmer from 'simmerjs';
import root from 'react-shadow';

window.simmer = new Simmer(window, {depth: 8});

// Function basically a copy of the mixpanel thing
let getSafeText = (el) => {
    if(!el.childNodes || !el.childNodes.length) return;
    let elText = '';
    el.childNodes.forEach((child) => {
        if(child.nodeType !== 3 || !child.textContent) return;
        elText += child.textContent.trim()
            .replace(/[\r\n]/g, ' ').replace(/[ ]+/g, ' ') // normalize whitespace
            .substring(0, 255)
    })
    return elText
}

class SelectElement extends Component {
    constructor(props) {
        super(props);
        this.state = {};
        this.onMouseOver = this.onMouseOver.bind(this);
        this.onKeyDown = this.onKeyDown.bind(this);
        this.Option = this.Option.bind(this);
    }
    drawBox(element) {
        if(!this.box) {
            this.box = document.createElement('div');
            document.body.appendChild(this.box)
        }
        let rect = element.getBoundingClientRect();
        this.box.style.display = 'block';
        this.box.style.position = 'absolute';
        this.box.style.top = parseInt(rect.top + window.pageYOffset) + 'px';
        this.box.style.left = parseInt(rect.left + window.pageXOffset) + 'px';
        this.box.style.width = parseInt(rect.right - rect.left) + 'px';
        this.box.style.height = parseInt(rect.bottom - rect.top) + 'px';
        this.box.style.background = 'red';
        this.box.style.opacity = '0.3';
    }
    onMouseOver(event) {
        this.drawBox(event.currentTarget);
        let res = simmer(event.currentTarget);
        // Turn tags into lower cases
        res = res.replace(/(^[A-Z]+| [A-Z]+)/g, (d) => d.toLowerCase())
        let tagName = event.currentTarget.tagName.toLowerCase();

        let selection = ['selector'];
        if(tagName == 'a') selection = ['href'];
        else if(tagName == 'button') selection = ['text'];
        this.setState({element: event.currentTarget, query: res, selection})
    }
    onKeyDown(event) {
        // stop selecting if esc key was pressed
        if(event.keyCode == 27) this.stop()
    }
    start() {
        document
            .querySelectorAll("a, button, input, select, textarea, label")
            .forEach((element) => {
                element.addEventListener('mouseover', this.onMouseOver, {capture: true})
            })
        document.addEventListener('keydown', this.onKeyDown)
    }
    stop() {
        this.box.style.display = 'none';
        document
            .querySelectorAll("a, button, input, select, textarea, label")
            .forEach((element) => {
                element.removeEventListener('mouseover', this.onMouseOver, {capture: true})
            })
        document.removeEventListener('keydown', this.onKeyDown)
    }
    Option(props) {
        return <div className={'form-group ' + (this.state.selection.indexOf(props.item) > -1 && 'selected')}>
            <label><input
                type="checkbox"
                name='selection'
                checked={this.state.selection.indexOf(props.item) > -1}
                value={props.item}
                onChange={(e) => {
                    if(e.target.checked) {
                        this.state.selection.push(props.item);
                    } else {
                        this.state.selection = this.state.selection.filter((i) => i != props.item)
                    }
                    this.setState({selection: this.state.selection})
                }}
                /> {props.label}</label>
            {props.item == 'selector' ?
                <textarea style={{width: '100%'}} className='form-control' value={props.value} /> :
                <input style={{width: '100%'}} className='form-control' value={props.value} />}
            {props.selector && <small className='form-text text-muted'>Matches {document.querySelectorAll(props.selector).length} elements</small>}
        </div>
    }
    render() {
        let tagName = this.state.element && this.state.element.tagName.toLowerCase()
        return <div>
            <button className='btn btn-success' onClick={() => this.start()}>
                Select element
            </button>
            {this.state.whatever}
            {this.state.element && <div>
                <br />
                {tagName == 'a' && <this.Option
                    item='href'
                    label='Link href'
                    value={this.state.element.getAttribute('href')}
                    selector={'a[href="' + this.state.element.getAttribute('href') +'"]'} />}
                {(tagName == 'button' || tagName == 'a') && <this.Option
                    item='text'
                    label='Text'
                    value={getSafeText(this.state.element)}
                     />}
                <this.Option
                    item='selector'
                    label='Selector'
                    value={this.state.query}
                    selector={this.state.query}
                    />
                <this.Option
                    item='url'
                    label='Match url'
                    value={window.location.pathname}
                     />
            </div>}
        </div>
    }
}

let styles = `
    .form-group { padding: 1rem 12px;margin: 0 }
    .form-group.selected { background: rgba(0, 0, 0, 0.1)}
    .form-group:not(:last-child) {border-bottom: 1px solid rgba(0, 0, 0, 0.1) }
`;
class App extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
        }
        this.fetchElements.call(this);
        console.log(styles)
    }
    fetchElements() {
        api.get('api/event/elements').then((elements) => this.setState({elements}))
    }

    render() {
        return <root.div style={{position: 'fixed', top: 0, zIndex: 999999999, right: 0, height: '100vh', overflowY: 'scroll', width: 280, background: 'white', borderLeft: '1px solid rgba(0, 0, 0, 0.1)', fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Roboto", "Oxygen", "Ubuntu", "Cantarell", "Fira Sans", "Droid Sans", "Helvetica Neue", sans-serif'}}>
            <link href="https://stackpath.bootstrapcdn.com/bootstrap/4.4.1/css/bootstrap.min.css" rel="stylesheet" crossorigin="anonymous" />
            <h2>PostHog</h2><br />
            <style>{styles}
            </style>
            <SelectElement />
        </root.div>
    }
}

window.ph_load_editor = function() {
    let container = document.createElement('div');
    document.body.appendChild(container);

    ReactDOM.render(<App />, container);
}
