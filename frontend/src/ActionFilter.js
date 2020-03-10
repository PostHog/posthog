import React, { Component } from 'react';
import { CloseButton, selectStyle, Card } from './utils';
import { Dropdown } from "./Dropdown";
import PropTypes from 'prop-types';
import Select, { components } from 'react-select';

class ActionSelectInfo extends Component {
    infoDiv = React.createRef()
    componentDidMount(prevProps) {
        if(!this.infoDiv.current) return;
        let rect = this.props.boundingRect;
        this.infoDiv.current.style.top = (rect.top - rect.height/2) + 'px';
        this.infoDiv.current.style.left = rect.left + rect.width + 'px';
        this.infoDiv.current.style.opacity = 1;
    }
    componentDidUpdate() {
        this.componentDidMount();
    }
    render() {
        let { action, isOpen } = this.props;
        if(!action) return null;
        return <div className='select-box-info' ref={this.infoDiv} style={{opacity: isOpen ? 1 : 0}}>
            <div style={{marginBottom: '0.5rem'}}>{action.name}</div>
            {action.steps.map((step, index) => <div>
                <Card key={step.id} style={{marginBottom: 0}}>
                    <div className='card-body'>
                        <strong>{step.event[0] == '$' ? step.event[1].toUpperCase() + step.event.slice(2) : step.event}</strong>
                        <ul style={{listStyle: 'none'}}>
                            {step.selector && <li>
                                CSS selector matches
                                <pre>{step.selector}</pre>
                            </li>}
                            {step.tag_name && <li>Tag name matches <pre>{step.tag_name}</pre></li>}
                            {step.text && <li>Text matches <pre>{step.text}</pre></li>}
                            {step.href && <li>Link HREF matches <pre>{step.href}</pre></li>}
                            {step.url && <li>URL {step.url_matching == 'contains' ? 'contains' : 'matches'} <pre>{step.url}</pre></li>}
                        </ul>
                    </div>
                </Card>
                {index < action.steps.length -1 && <div className='secondary' style={{textAlign: 'center', margin: '1rem'}}>OR</div>}
            </div>)}
        </div>
    }
}
class ActionSelectBox extends Component {
    constructor(props) {
        super(props)
        this.state = {}
    }
    actionContains(action, event) {
        return action.steps.filter(step => step.event == event).length > 0
    }
    
    Option = props => {
        return <div
            onMouseOver={e => this.setState({
                infoOpen: true,
                infoBoundingRect: e.target.getBoundingClientRect(),
                infoActionId: props.value
            })}
            onMouseOut={e => {
                this.setState({infoOpen: false})
            }}
        >
            <components.Option {...props} />
        </div>
    }
    groupActions = (actions) => {
        let data = [
            {'label': 'Autocapture', options: []},
            {'label': 'Event', options: []},
            {'label': 'Pageview', options: []}
        ]
        actions.map(action => {
            let format = {label: action.name, value: action.id};
            if(this.actionContains(action, '$autocapture')) data[0].options.push(format);
            if(this.actionContains(action, '$pageview')) data[2].options.push(format);
            if(!this.actionContains(action, '$autocapture') && !this.actionContains(action, '$pageview')) data[1].options.push(format);
        })
        return data;
    }
    render() {
        let { action, actions, onClose, onChange } = this.props;
        return <div className='select-box'>
            {action.id && <a href={'/action/' + action.id} target="_blank">Edit "{action.name}" <i className='fi flaticon-export' /></a>}
            <ActionSelectInfo
                isOpen={this.state.infoOpen}
                boundingRect={this.state.infoBoundingRect}
                action={actions.filter(a => a.id == this.state.infoActionId)[0]}
                />
            <Select
                onBlur={(e) => {
                    if(e.relatedTarget && e.relatedTarget.tagName == 'A') return;
                    onClose()
                }}
                onChange={(item) => onChange(item.value)}
                defaultMenuIsOpen={true}
                autoFocus={true}
                // menuIsOpen={true}
                styles={selectStyle}
                components={{Option: this.Option}}
                options={this.groupActions(actions)} />
        </div>
    }
}
ActionSelectBox.propTypes = {
    actionFilters: PropTypes.array.isRequired,
    onChange: PropTypes.func.isRequired,
    actions: PropTypes.array.isRequired,
    action: PropTypes.object.isRequired
}
export class ActionFilter extends Component {
    constructor(props) {
        super(props);
        this.state = {
            actionFilters: props.actionFilters
        };
        this.Row = this.Row.bind(this);
        this.Math = this.Math.bind(this);
    }
    onMathSelect(index, math) {
        let { actionFilters } = this.state;
        actionFilters[index].math = math;
        this.props.onChange(actionFilters);
    }
    Math(props) {
        let items = ['Total', 'DAU'];
        return <Dropdown title={items[items.map(i => i.toLowerCase()).indexOf(props.math)] || 'Total'} buttonClassName='btn btn-sm btn-light' style={{ marginLeft: 32, marginRight: 16 }}>
            <a href='#' className='dropdown-item' onClick={() => this.onMathSelect.call(this, props.index, 'total')}>Total</a>
            <a href='#' className='dropdown-item' onClick={() => this.onMathSelect.call(this, props.index, 'dau')}>DAU</a>
        </Dropdown>;
    }
    Row(props) {
        let { selected, actionFilters } = this.state;
        let { actions } = this.props;
        let { action, filter, index } = props;
        return <div>
            <button className='filter-action' onClick={() => this.setState({ selected: action.id })} style={{ border: 0, padding: 0, fontWeight: 500, borderBottom: '1.5px dotted var(--blue)' }}>
                {action.name || 'Select action'}
            </button>
            <this.Math math={filter.math} index={index} />
            <CloseButton onClick={() => {
                actionFilters.splice(action.index, 1);
                this.props.onChange(actionFilters);
            }} style={{ float: 'none', marginLeft: 8, position: 'absolute', marginTop: 3 }} />
            {(!action.id, selected == action.id) && <ActionSelectBox
                actions={actions}
                action={action}
                onChange={(actionId) => {
                    actionFilters[index] = {id: actionId};
                    this.props.onChange(actionFilters)
                }}
                index={index}
                onClose={() => this.setState({ selected: false })}
                actionFilters={actionFilters} />
            }
        </div>;
    }
    componentDidUpdate(prevProps) {
        if (prevProps.actionFilters != this.props.actionFilters)
            this.setState({ actionFilters: this.props.actionFilters });
    }
    render() {
        let { actions } = this.props;
        let { actionFilters } = this.state;
        return actions ? <div>
            {actionFilters && actionFilters.map((action_filter, index) => {
                let action = actions.filter(action => action.id == action_filter.id)[0] || {};
                return <this.Row action={action} filter={action_filter} key={index} index={index} />;
            })}
            <button className='btn btn-sm btn-outline-success' onClick={() => this.setState({ actionFilters: [...actionFilters, { id: null }] })} style={{ marginTop: '0.5rem' }}>
                Add action
            </button>
        </div> : null;
    }
}
