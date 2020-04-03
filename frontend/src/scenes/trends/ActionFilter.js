import React, { Component } from 'react'
import { CloseButton, groupActions, groupEvents } from '../../lib/utils'
import { Dropdown } from '../../lib/components/Dropdown'
import { ActionSelectPanel, ActionSelectTabs } from '../../lib/components/ActionSelectBox'
import { Link } from 'react-router-dom'

export function ActionFilterRow(props) {
    let { math, index, name, dropDownCondition, onClick, onClose, onMathSelect } = props
    return (
        <div>
            <button
                className="filter-action"
                onClick={onClick}
                style={{
                    border: 0,
                    padding: 0,
                    fontWeight: 500,
                    borderBottom: '1.5px dotted var(--blue)',
                }}
            >
                {name || 'Select action'}
            </button>
            <MathSelector math={math} index={index} onMathSelect={onMathSelect} />
            <CloseButton
                onClick={onClose}
                style={{
                    float: 'none',
                    marginLeft: 8,
                    position: 'absolute',
                    marginTop: 3,
                }}
            />
            {dropDownCondition() && props.children}
        </div>
    )
}

export function MathSelector(props) {
    let items = ['Total', 'DAU']
    return (
        <Dropdown
            title={items[items.map(i => i.toLowerCase()).indexOf(props.math)] || 'Total'}
            buttonClassName="btn btn-sm btn-light"
            style={{ marginLeft: 32, marginRight: 16 }}
        >
            <a href="#" className="dropdown-item" onClick={() => props.onMathSelect(props.index, 'total')}>
                Total
            </a>
            <a href="#" className="dropdown-item" onClick={() => props.onMathSelect(props.index, 'dau')}>
                DAU
            </a>
        </Dropdown>
    )
}

export class ActionFilter extends Component {
    constructor(props) {
        super(props)
        this.state = {
            actionFilters: props.actionFilters,
            eventFilters: props.eventFilters,
        }
    }

    componentDidUpdate(prevProps) {
        if (prevProps.actionFilters != this.props.actionFilters)
            this.setState({ actionFilters: this.props.actionFilters })
    }

    _renderRow(action_filter, index) {
        let { actions } = this.props
        let { actionFilters, selected } = this.state

        let action = actions.filter(action => action.id == action_filter.id)[0] || {}
        let dropDownCondition = () => this.state.selected == action.id
        let onClick = () => {
            if (selected == action.id) {
                this.setState({
                    selected: null,
                })
            } else {
                this.setState({
                    selected: action.id,
                })
            }
        }
        let onClose = () => {
            actionFilters.splice(index, 1)
            this.props.onChange(actionFilters)
        }
        let onMathSelect = (index, math) => {
            let { actionFilters } = this.state
            actionFilters[index].math = math
            this.props.onChange(actionFilters)
        }
        return (
            <ActionFilterRow
                name={action.name}
                value={action.id}
                dropDownCondition={dropDownCondition}
                onClick={onClick}
                onClose={onClose}
                onMathSelect={onMathSelect}
                math={action_filter.math}
                key={index}
                index={index}
            >
                <ActionSelectTabs>
                    <ActionSelectPanel
                        title="Actions"
                        options={groupActions(actions)}
                        defaultMenuIsOpen={true}
                        onSelect={item => {
                            actionFilters[index] = { id: item.value }
                            this.props.onChange(actionFilters)
                        }}
                        onHover={value => actions.filter(a => a.id == value)[0]}
                        active={{
                            label: action.name,
                            value: action.id,
                        }}
                    >
                        {action.id && (
                            <a href={'/action/' + action.id} target="_blank">
                                Edit "{action.name}" <i className="fi flaticon-export" />
                            </a>
                        )}
                    </ActionSelectPanel>
                </ActionSelectTabs>
            </ActionFilterRow>
        )
    }

    render() {
        let { actions } = this.props
        let { actionFilters, selected } = this.state
        return actions && actions.length > 0 ? (
            <div>
                {actionFilters &&
                    actionFilters.map((action_filter, index) => {
                        return this._renderRow(action_filter, index)
                    })}
                <button
                    className="btn btn-sm btn-outline-success"
                    onClick={() =>
                        this.setState({
                            actionFilters: [...(actionFilters || []), { id: -1 }],
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
