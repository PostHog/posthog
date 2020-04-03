import React, { Component } from 'react'
import { CloseButton, groupActions, groupEvents } from '../../lib/utils'
import { Dropdown } from '../../lib/components/Dropdown'
import { ActionSelectPanel, ActionSelectTabs } from '../../lib/components/ActionSelectBox'
import { Link } from 'react-router-dom'

export class ActionFilter extends Component {
    constructor(props) {
        super(props)
        this.state = {
            actionFilters: props.actionFilters,
            eventFilters: props.eventFilters,
            activeTab: 'actions',
        }
        this.Row = this.Row.bind(this)
        this.Math = this.Math.bind(this)
    }
    onMathSelect(index, math) {
        let { actionFilters } = this.state
        actionFilters[index].math = math
        this.props.onChange(actionFilters)
    }
    Math(props) {
        let items = ['Total', 'DAU']
        return (
            <Dropdown
                title={items[items.map(i => i.toLowerCase()).indexOf(props.math)] || 'Total'}
                buttonClassName="btn btn-sm btn-light"
                style={{ marginLeft: 32, marginRight: 16 }}
            >
                <a
                    href="#"
                    className="dropdown-item"
                    onClick={() => this.onMathSelect.call(this, props.index, 'total')}
                >
                    Total
                </a>
                <a href="#" className="dropdown-item" onClick={() => this.onMathSelect.call(this, props.index, 'dau')}>
                    DAU
                </a>
            </Dropdown>
        )
    }

    actionContains(action, event) {
        return action.steps.filter(step => step.event == event).length > 0
    }

    Row(props) {
        let { selected, actionFilters, activeTab } = this.state
        let { actions, events } = this.props
        let { action, event, filter, index } = props
        return (
            <div>
                <button
                    className="filter-action"
                    onClick={() => this.setState({ selected: this.state.selected ? false : action.id })}
                    style={{
                        border: 0,
                        padding: 0,
                        fontWeight: 500,
                        borderBottom: '1.5px dotted var(--blue)',
                    }}
                >
                    {action.name || 'Select action'}
                </button>
                <this.Math math={filter.math} index={index} />
                <CloseButton
                    onClick={() => {
                        actionFilters.splice(index, 1)
                        this.props.onChange(actionFilters)
                    }}
                    style={{
                        float: 'none',
                        marginLeft: 8,
                        position: 'absolute',
                        marginTop: 3,
                    }}
                />
                {(!action.id, selected == action.id) && (
                    <ActionSelectTabs>
                        <ActionSelectPanel
                            title="Actions"
                            options={groupActions(actions)}
                            defaultMenuIsOpen={true}
                            onSelect={value => {
                                actionFilters[index] = { id: value }
                                this.props.onChange(actionFilters)
                            }}
                            onHover={value => actions.filter(
                                a => a.id == value
                            )[0]}
                        >
                            {action.id && (
                                <a href={'/action/' + action.id} target="_blank">
                                    Edit "{action.name}"{' '}
                                    <i className="fi flaticon-export" />
                                </a>
                            )}
                        </ActionSelectPanel>
                        {/* <ActionSelectPanel
                            title="Events"
                            options={this.groupEvents(events)}
                            defaultMenuIsOpen={true}
                            onSelect={value => {
                                actionFilters[index] = { id: value }
                                this.props.onChange(actionFilters)
                            }}
                            onHover={value => events.filter(
                                e => e.name == value
                            )[0]}
                        ></ActionSelectPanel> */}
                    </ActionSelectTabs>
                )}
            </div>
        )
    }
    componentDidUpdate(prevProps) {
        if (prevProps.actionFilters != this.props.actionFilters)
            this.setState({ actionFilters: this.props.actionFilters })
    }
    render() {
        let { actions } = this.props
        let { actionFilters } = this.state
        return actions && actions.length > 0 ? (
            <div>
                {actionFilters &&
                    actionFilters.map((action_filter, index) => {
                        let action = actions.filter(action => action.id == action_filter.id)[0] || {}
                        return <this.Row action={action} filter={action_filter} key={index} index={index} />
                    })}
                <button
                    className="btn btn-sm btn-outline-success"
                    onClick={() =>
                        this.setState({
                            actionFilters: [...(actionFilters || []), { id: null }],
                        })
                    }
                    style={{ marginTop: '0.5rem' }}
                >
                    Add action
                </button>
            </div>
        ) : (
            <div>
                You don't have any actions defined yet. <Link to="/action">Click here to define an action.</Link>
            </div>
        )
    }
}
