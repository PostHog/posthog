import React, { Component } from 'react';
import api from './Api';
import { uuid } from './utils';
import { AppEditorLink } from "./Actions";
import PropTypes from 'prop-types';
import Select from 'react-select';


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
class EventName extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
        }
        this.fetchNames.call(this);
    }
    fetchNames() {
        api.get('api/event/names').then((names) => this.setState({
            names: names.map((name) => ({
                value: name.name,
                label: name.name + ' (' + name.count + ' events)'
            })).filter((item) => item.value != '$autocapture' && item.value != '$pageview')
        }))
    }
    render() {
        if(this.props.value == '$autocapture' || this.props.value == '$pageview') return <input type="text" disabled value={this.props.value} className='form-control' />;
        return this.state.names ? <Select
            options={this.state.names}
            isSearchable={true}
            isClearable={true}
            onChange={this.props.onChange}
            value={this.props.value && this.state.names.filter((item) => this.props.value == item.value)[0]}
            /> : null;
    }
}
EventName.propTypes = {
    onChange: PropTypes.func.isRequired,
    value: PropTypes.string.isRequired
}
class ActionStep extends Component {
    constructor(props) {
        super(props);
        this.state = {
            step: props.step,
            selection: Object.keys(props.step).filter((key) => key != 'id' && key != 'isNew' && props.step[key])
        };
        this.onMouseOver = this.onMouseOver.bind(this);
        this.onKeyDown = this.onKeyDown.bind(this);
        this.Option = this.Option.bind(this);
        this.sendStep = this.sendStep.bind(this);
        this.AutocaptureFields = this.AutocaptureFields.bind(this);
        this.TypeSwitcher = this.TypeSwitcher.bind(this);
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
        this.box.style.background = '#007bff';
        this.box.style.opacity = '0.5';
        this.box.style.zIndex = '9999999999';
    }
    onMouseOver(event) {
        let el = event.currentTarget;
        this.drawBox(el);
        let query = this.props.simmer(el);
        // Turn tags into lower cases
        query = query.replace(/(^[A-Z]+| [A-Z]+)/g, (d) => d.toLowerCase())
        let tagName = el.tagName.toLowerCase();

        let selection = ['selector'];
        if(tagName == 'a') selection = ['href', 'selector'];
        else if(tagName == 'button') selection = ['text', 'selector'];
        else if(el.getAttribute('name')) selection = ['name', 'selector'];
        let step = {
            ...this.props.step,
            event: '$autocapture',
            tag_name: tagName,
            href: el.getAttribute('href') || '',
            name: el.getAttribute('name') || '',
            text: getSafeText(el) || '',
            selector: query || '',
            url: window.location.protocol + '//' + window.location.host + window.location.pathname
        }
        this.setState({
            element: el,
            selection}, () => this.sendStep(step))
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
        document.addEventListener('keydown', this.onKeyDown);
        document.body.style.transition = '0.7s box-shadow';
        // document.body.style.boxShadow = 'inset 0 0px 13px -2px #dc3545';
        document.body.style.boxShadow = 'inset 0 0px 30px -5px #007bff';
        this.box.addEventListener('click', this.stop)
    }
    stop() {
        this.box.style.display = 'none';
        document.body.style.boxShadow = 'none';
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
            this.props.step[props.item] = e.target.value;
            this.sendStep(this.props.step);
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
                    this.setState({selection: this.state.selection}, () => this.sendStep(this.props.step))
                }}
                /> {props.label}</label>
            {props.item == 'selector' ?
                <textarea className='form-control' onChange={onChange} value={this.props.step[props.item]} /> :
                <input className='form-control' onChange={onChange} value={this.props.step[props.item]} />}
            {props.selector && this.props.isEditor && <small className='form-text text-muted'>Matches {document.querySelectorAll(props.selector).length} elements</small>}
        </div>
    }
    TypeSwitcher() {
        let { step, isEditor } = this.props;
        return <div>
            <label>Action type</label><br />
            <div className='btn-group'>
                <button
                    type="button"
                    onClick={() => this.sendStep({...step, event: '$autocapture'})}
                    className={'btn ' + (step.event == '$autocapture' ? 'btn-secondary' : 'btn-light')}>
                    Match element
                </button>
                <button
                    type="button"
                    onClick={() => this.sendStep({...step, event: ''})}
                    className={'btn ' + (step.event &&step.event != '$autocapture' && step.event != '$pageview' ? 'btn-secondary' : 'btn-light')}>
                    Match event
                </button>
                <button
                    type="button"
                    onClick={() => { 
                        this.setState({selection: ['url']}, () => this.sendStep({
                                ...step,
                                event: '$pageview',
                                url: isEditor ? window.location.protocol + '//' + window.location.host + window.location.pathname : null
                            })
                        )
                    }} className={'btn ' + (step.event == '$pageview' ? 'btn-secondary' : 'btn-light')}>
                    Page view
                </button>
            </div>
            {step.event != null && step.event != '$autocapture' && step.event != '$pageview' && <div style={{marginTop: '2rem'}}><label>Event name</label>
                <EventName
                    value={step.event}
                    onChange={(item) => this.sendStep({...step, event: item.value})} />
            </div>}
        </div>
    }
    AutocaptureFields() {
        let { element } = this.state;
        let { step, user, actionId, isEditor } = this.props;
        return <div>
            {!isEditor && <AppEditorLink user={user} actionId={actionId} style={{marginBottom: '1rem'}} className='btn btn-sm btn-light'>Select element on site <i className='fi flaticon-export' /></AppEditorLink>}
            {(!isEditor || step.href) && <this.Option
                item='href'
                label='Link href'
                selector={this.state.element && 'a[href="' + this.state.element.getAttribute('href') +'"]'} />}
            {(!isEditor || step.text) && <this.Option
                item='text'
                label='Text'
                />}
            <this.Option
                item='selector'
                label='Selector'
                selector={step.selector}
                />
        </div>
    }
    render() {
        let { step, isEditor } = this.props;
        return <div style={{borderBottom: '1px solid rgba(0, 0, 0, 0.1)', paddingBottom: '1rem'}}>
            {(!isEditor || step.event == '$autocapture') && <button style={{marginTop: -3}} type="button" className="close pull-right" aria-label="Close" onClick={this.props.onDelete}>
                <span aria-hidden="true">&times;</span>
            </button>}
            {!isEditor && <this.TypeSwitcher />}
            <div style={{margin: (isEditor ? '0 -12px' : '')}}>
                <br />

                {this.props.isEditor && <button type="button" className='btn btn-sm btn-secondary' style={{margin: '0 0 1rem 15px'}} onClick={() => this.start()}>
                    Inspect element
                </button>}
                {step.event == '$autocapture' && <this.AutocaptureFields />}
                {(step.event == '$autocapture' || step.event == '$pageview') && <this.Option
                    item='url'
                    label='Only match if URL contains'
                    />}
            </div>
        </div>
    }
}
ActionStep.propTypes = {
    isEditor: PropTypes.bool,
    step: PropTypes.object,
    simmer: PropTypes.func
}

export class ActionEdit extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            action: {name: '', steps: []}
        }
        this.temporaryToken = props.temporaryToken ? '?temporary_token=' + props.temporaryToken : ''
        this.fetchAction.call(this);
        this.onSubmit = this.onSubmit.bind(this);
    }
    fetchAction() {
        if(this.props.actionId) {
            return api.get(this.props.apiURL + 'api/action/' + this.props.actionId + '/' + this.temporaryToken).then((action) => this.setState({action}))
        }
        // If it's a new action, add an empty step
        this.state.action = {name: '', steps: [{isNew: uuid(), }]}
    }
    onSubmit(event, createNew) {
        if(!event.target.form.checkValidity()) return;
        let save = (action) => {
            if(createNew) {
                this.setState({error: false, saved: true, action: {name: '', steps: [{isNew: uuid()}]}})
                if(this.props.isEditor) sessionStorage.removeItem('editorActionId');
            } else {
                this.setState({action: {...this.state.action, id: action.id}})
                if(this.props.isEditor) sessionStorage.setItem('editorActionId', action.id);
                this.setState({error: false, saved: true})
            }
            this.props.onSave && this.props.onSave(action);
        }
        let error = (detail) => {
            if(detail.detail == 'action-exists') this.setState({saved: false, error: 'action-exists', error_id: detail.id})
        }
        let steps = this.state.action.steps.map((step) => {
            if(step.event == '$pageview') step.selection = ['url'];
            if(step.event != '$pageview' && step.event != '$autocapture') step.selection = [];
            if(!step.selection) return step;
            let data = {};
            Object.keys(step).map((key) => {
                data[key] = (key == 'id' || key == 'event' || step.selection.indexOf(key) > -1) ? step[key] : null;
            })
            return data;
        })
        if(this.state.action.id) {
            return api.update(this.props.apiURL + 'api/action/' + this.state.action.id + '/' + this.temporaryToken, {name: this.state.action.name, steps}).then(save).catch(error)
        }
        api.create(this.props.apiURL + 'api/action/' + this.temporaryToken, {name: this.state.action.name, steps}).then(save).catch(error)
    }
    render() {
        let action = this.state.action;
        let { isEditor, simmer } = this.props;
        return <form onSubmit={(e) => e.preventDefault()}>
            <label>Action name</label>
            <input autoFocus required className='form-control' placeholder="user signed up" value={action.name} onChange={(e) => this.setState({action: {...action, name: e.target.value}})} />
            <br />
            {action.steps.map((step, index) => <ActionStep
                key={step.id || step.isNew}
                step={step}
                isEditor={isEditor}
                actionId={action.id}
                user={this.props.user}
                simmer={simmer}
                onDelete={() => {
                    action.steps = action.steps.filter((s) => s.id != step.id)
                    this.setState({action: action});
                }}
                onChange={(newStep) => {
                    action.steps = action.steps.map((s) => ((step.id && s.id == step.id) || (step.isNew && s.isNew == step.isNew)) ? {id: step.id, isNew: step.isNew, ...newStep} : s);
                    this.setState({action: action});
                }} />
            )}
            <br />
            <button
                type="button"
                className='btn btn-secondary btn-sm'
                onClick={() => {
                    action.steps.push({isNew: uuid()});
                    this.setState({action: action})
                }}>Add another match group</button>
            <br /><br />
            {(!isEditor || (action.steps.length > 0)) && <div className='btn-group'>
                <button type="submit" onClick={(e) => this.onSubmit(e)} className='btn btn-success btn-sm'>Save action</button>
                {this.props.isEditor && <button type="submit" onClick={(e) => this.onSubmit(e, true)} className='btn btn-secondary btn-sm'>Save & new action</button>}
            </div>}
            {this.state.saved && <p className='text-success'>Action saved. <a href={this.props.apiURL + 'action/' + action.id}>Click here to see all events.</a></p>}
            {this.state.error && <p className='text-danger'>Action with this name already exists. <a href={this.props.apiURL + 'action/' + this.state.error_id}>Click here to edit.</a></p>}
        </form>
    }
}
ActionEdit.propTypes = {
    user: PropTypes.object,
    isEditor: PropTypes.bool,
    simmer: PropTypes.func
}
