import React, { Component } from "react";
import ReactDOM from "react-dom";
import api from '../Api';
import { uuid } from '../utils';
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
        this.state = {
            step: props.step,
            selection: Object.keys(props.step).filter((key) => key != 'id' && key != 'isNew')
        };
        this.onMouseOver = this.onMouseOver.bind(this);
        this.onKeyDown = this.onKeyDown.bind(this);
        this.Option = this.Option.bind(this);
        this.sendStep = this.sendStep.bind(this);
        this.stop = this.stop.bind(this);

        this.box = document.createElement('div');
        document.body.appendChild(this.box)
    }
    drawBox(element) {
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
        let el = event.currentTarget;
        this.drawBox(el);
        let query = simmer(el);
        // Turn tags into lower cases
        query = query.replace(/(^[A-Z]+| [A-Z]+)/g, (d) => d.toLowerCase())
        let tagName = el.tagName.toLowerCase();

        let selection = ['selector'];
        if(tagName == 'a') selection = ['href'];
        else if(tagName == 'button') selection = ['text'];
        else if(el.getAttribute('name')) selection = ['name'];
        let step = {
            id: this.state.step.id,
            isNew: this.state.step.isNew,
            href: el.getAttribute('href'),
            name: el.getAttribute('name'),
            text: getSafeText(el),
            selector: query,
            url: window.location.protocol + '//' + window.location.host + window.location.pathname
        }
        this.setState({
            element: el,
            step,
            query,
            selection})
        this.sendStep(step);
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
        this.box.addEventListener('click', this.stop)
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
    sendStep(step) {
        step.selection = this.state.selection;
        this.props.onChange(step)
    }
    Option(props) {
        let onChange = (e) => {
            this.state.step[props.item] = e.target.value;
            this.setState({step: this.state.step})
            this.sendStep(this.state.step);
        }
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
                    this.setState({selection: this.state.selection}, () => this.sendStep(this.state.step))
                }}
                /> {props.label}</label>
            {props.item == 'selector' ?
                <textarea className='form-control' onChange={onChange} value={this.state.step[props.item]} /> :
                <input className='form-control' onChange={onChange} value={this.state.step[props.item]} />}
            {props.selector && this.props.isEditor && <small className='form-text text-muted'>Matches {document.querySelectorAll(props.selector).length} elements</small>}
        </div>
    }

    render() {
        return <div style={{borderBottom: '1px solid rgba(0, 0, 0, 0.1)', paddingBottom: '1rem'}}>
            <button style={{marginTop: -3}} type="button" className="close pull-right" aria-label="Close" onClick={this.props.onDelete}>
                <span aria-hidden="true">&times;</span>
            </button>
            {this.props.isEditor && <button type="button" className='btn btn-sm btn-light' onClick={() => this.start()}>
                inspect element
            </button>}
            <div style={{margin: (this.props.isEditor ? '0 -12px' : '')}}>
                <br />
                {this.state.step.href && <this.Option
                    item='href'
                    label='Link href'
                    selector={this.state.element && 'a[href="' + this.state.element.getAttribute('href') +'"]'} />}
                {this.state.step.name && <this.Option
                    item='name'
                    label='Element name'
                    selector={this.state.element && '[name="' + this.state.element.getAttribute('name') + '"]'} />}
                {this.state.step.text && <this.Option
                    item='text'
                    label='Text'
                     />}
                {this.state.step.selector && <this.Option
                    item='selector'
                    label='Selector'
                    selector={this.state.step.selector}
                    />}
                {this.state.step.url && <this.Option
                    item='url'
                    label='Match url'
                    />}
            </div>
        </div>
    }
}

export class EditAction extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            action: {
                steps: []
            }
        }
        this.fetchAction.call(this);
        this.onSubmit = this.onSubmit.bind(this);
    }
    fetchAction() {
        if(this.props.actionId) {
            return api.get('api/action/' + this.props.actionId).then((action) => this.setState({action}))
        }
        // If it's a new action, add an empty step
        this.setState({action: {steps: [{isNew: uuid()}]}})
    }
    onSubmit(event, createNew) {
        if(!event.target.form.checkValidity()) return;
        let save = (action) => {
            if(createNew) {
                this.setState({error: false, saved: true, action: {name: '', steps: [{isNew: uuid()}]}})
                sessionStorage.removeItem('editorActionId');
            } else {
                this.setState({action: {...this.state.action, id: action.id}})
                if(this.props.isEditor) sessionStorage.setItem('editorActionId', action.id);
                setTimeout(() => this.setState({error: false, saved: true}), 500)
            }
        }
        let error = (detail) => {
            if(detail.detail == 'action-exists') this.setState({saved: false, error: 'action-exists', error_id: detail.id})
        }
        let steps = this.state.action.steps.map((step) => {
            if(!step.selection) return step;
            let data = {};
            Object.keys(step).map((key) => {
                data[key] = (key == 'id' || step.selection.indexOf(key) > -1) ? step[key] : null;
            })
            return data;
        })
        if(this.state.action.id) {
            return api.update('api/action/' + this.state.action.id, {name: this.state.action.name, steps}).then(save).catch(error)
        }
        api.create('api/action', this.state.action, {name: this.state.action.name, steps}).then(save).catch(error)
    }
    render() {
        return <form onSubmit={(e) => e.preventDefault()}>
            <label>Action name</label>
            <input required className='form-control' placeholder="user signed up" value={this.state.action.name} onChange={(e) => this.setState({action: {...this.state.action, name: e.target.value}})} />
            <br />
            {this.state.action.steps.map((step, index) => <SelectElement
                key={step.id || step.isNew}
                step={step}
                isEditor={this.props.isEditor}
                onDelete={() => {
                    this.state.action.steps = this.state.action.steps.filter((s) => s.id != step.id)
                    this.setState({action: this.state.action});
                }}
                onChange={(newStep) => {
                    this.state.action.steps = this.state.action.steps.map((s) => ((step.id && s.id == step.id) || (step.isNew && s.isNew == step.isNew)) ? {id: step.id, isNew: step.isNew, ...newStep} : s);
                    this.setState({action: this.state.action});
                }} />
            )}
            <br />
            <button
                type="button"
                className='btn btn-light btn-sm'
                onClick={() => {
                    this.state.action.steps.push({isNew: uuid()});
                    this.setState({action: this.state.action})
                }}>Add another element</button>
            <br /><br />
            <div className='btn-group'>
                <button type="submit" onClick={(e) => this.onSubmit(e)} className='btn btn-success'>Save action</button>
                {this.props.isEditor && <button type="submit" onClick={(e) => this.onSubmit(e, true)} className='btn btn-light'>Save & new action</button>}
            </div>
            <br />
            {this.state.saved && <p className='text-success'>Action saved</p>}
            {this.state.error && <p className='text-danger'>Action with this name already exists. <a href={'https://app.posthog.com/action/' + this.state.error_id}>Click here to edit.</a></p>}
        </form>
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
    }
    render() {
        return <root.div style={{position: 'fixed', top: 0, zIndex: 999999999, padding: 12, right: 0, height: '100vh', overflowY: 'scroll', width: 280, background: 'white', borderLeft: '1px solid rgba(0, 0, 0, 0.1)', fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Roboto", "Oxygen", "Ubuntu", "Cantarell", "Fira Sans", "Droid Sans", "Helvetica Neue", sans-serif'}}>
            <link href="https://stackpath.bootstrapcdn.com/bootstrap/4.4.1/css/bootstrap.min.css" rel="stylesheet" crossorigin="anonymous" />
            <style>{styles}</style>
            <h2>PostHog</h2><br />
            <EditAction actionId={sessionStorage.getItem('editorActionId')} isEditor={true} />
        </root.div>
    }
}

window.ph_load_editor = function() {
    let container = document.createElement('div');
    document.body.appendChild(container);

    ReactDOM.render(<App />, container);
}
