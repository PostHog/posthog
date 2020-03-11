import React, { Component } from 'react'
import { CloseButton, selectStyle, Card } from '../../lib/utils'
import { Dropdown } from '../../lib/components/Dropdown'
import { ActionSelectBox } from './ActionSelectBox'

export class ActionFilter extends Component {
    constructor(props) {
        super(props)
        this.state = {
            actionFilters: props.actionFilters,
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
                title={
                    items[
                        items.map(i => i.toLowerCase()).indexOf(props.math)
                    ] || 'Total'
                }
                buttonClassName="btn btn-sm btn-light"
                style={{ marginLeft: 32, marginRight: 16 }}
            >
                <a
                    href="#"
                    className="dropdown-item"
                    onClick={() =>
                        this.onMathSelect.call(this, props.index, 'total')
                    }
                >
                    Total
                </a>
                <a
                    href="#"
                    className="dropdown-item"
                    onClick={() =>
                        this.onMathSelect.call(this, props.index, 'dau')
                    }
                >
                    DAU
                </a>
            </Dropdown>
        )
    }
    Row(props) {
        let { selected, actionFilters } = this.state
        let { actions } = this.props
        let { action, filter, index } = props
        return (
            <div>
                <button
                    className="filter-action"
                    onClick={() => this.setState({ selected: action.id })}
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
                        actionFilters.splice(action.index, 1)
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
                    <ActionSelectBox
                        actions={actions}
                        action={action}
                        onChange={actionId => {
                            actionFilters[index] = { id: actionId }
                            this.props.onChange(actionFilters)
                        }}
                        index={index}
                        onClose={() => this.setState({ selected: false })}
                        actionFilters={actionFilters}
                    />
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
        return actions ? (
            <div>
                {actionFilters &&
                    actionFilters.map((action_filter, index) => {
                        let action =
                            actions.filter(
                                action => action.id == action_filter.id
                            )[0] || {}
                        return (
                            <this.Row
                                action={action}
                                filter={action_filter}
                                key={index}
                                index={index}
                            />
                        )
                    })}
                <button
                    className="btn btn-sm btn-outline-success"
                    onClick={() =>
                        this.setState({
                            actionFilters: [...actionFilters, { id: null }],
                        })
                    }
                    style={{ marginTop: '0.5rem' }}
                >
                    Add action
                </button>
            </div>
        ) : null
    }
}
