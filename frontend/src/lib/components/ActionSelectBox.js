import React, { Component } from 'react'
import Select, { components } from 'react-select'
import { ActionSelectInfo } from '../../scenes/trends/ActionSelectInfo'
import { selectStyle } from '../utils'
import PropTypes from 'prop-types'
import ActionSelectTab from './ActionSelectTab'

export class ActionSelectTabs extends Component {
    constructor(props) {
        super(props)
        this.state = {
            activeTab: props.children[0].props.title,
            labels: props.children.map(child => child.props.title),
        }
    }

    onTabSelect = tab => {
        this.setState({
            activeTab: tab,
        })
    }

    render() {
        let { activeTab, labels } = this.state
        let { children } = this.props
        return (
            <div className="select-box" style={{ padding: 0 }}>
                <ActionSelectTab
                    entityType={activeTab}
                    allTypes={labels}
                    chooseEntityType={this.onTabSelect}
                ></ActionSelectTab>
                {children.map(child => {
                    if (child.props.title !== activeTab) return undefined
                    return child
                })}
            </div>
        )
    }
}

export class ActionSelectPanel extends Component {
    state = {
        infoOpen: false,
    }

    Option = props => {
        return (
            <div
                onMouseOver={e =>
                    this.setState({
                        infoOpen: true,
                        infoBoundingRect: e.target.getBoundingClientRect(),
                        infoActionId: props.value,
                    })
                }
                onMouseOut={e => {
                    this.setState({ infoOpen: false })
                }}
            >
                <components.Option {...props} />
            </div>
        )
    }

    render() {
        return (
            <div style={{ padding: '1rem' }}>
                {/* {action.id && (
                        <a href={'/action/' + action.id} target="_blank">
                            Edit "{action.name}"{' '}
                            <i className="fi flaticon-export" />
                        </a>
                    )} */}
                {this.state.infoOpen && (
                    <ActionSelectInfo
                        isOpen={this.state.infoOpen}
                        boundingRect={this.state.infoBoundingRect}
                        entity={this.props.onHover(this.state.infoActionId)}
                    />
                )}
                <Select
                    onBlur={e => {
                        if (e.relatedTarget && e.relatedTarget.tagName == 'A') return
                        this.setState({ infoOpen: false })
                        // if (onClose) onClose()
                    }}
                    onChange={this.props.onSelect}
                    defaultMenuIsOpen={this.props.defaultMenuIsOpen}
                    autoFocus={true}
                    value={null}
                    className="select-box-select"
                    styles={selectStyle}
                    components={{ Option: this.Option }}
                    options={this.props.options}
                />
            </div>
        )
    }
}

ActionSelectPanel.propTypes = {
    options: PropTypes.array.isRequired,
    defaultMenuIsOpen: PropTypes.bool.isRequired,
    onSelect: PropTypes.func.isRequired,
    title: PropTypes.string.isRequired,
    onHover: PropTypes.func.isRequired,
}

export class ActionSelectBox extends Component {
    constructor(props) {
        super(props)
        this.state = {}
    }
    actionContains(action, event) {
        return action.steps.filter(step => step.event == event).length > 0
    }

    Option = props => {
        return (
            <div
                onMouseOver={e =>
                    this.setState({
                        infoOpen: true,
                        infoBoundingRect: e.target.getBoundingClientRect(),
                        infoActionId: props.value,
                    })
                }
                onMouseOut={e => {
                    this.setState({ infoOpen: false })
                }}
            >
                <components.Option {...props} />
            </div>
        )
    }
    groupActions = actions => {
        let data = [
            { label: 'Autocapture', options: [] },
            { label: 'Event', options: [] },
            { label: 'Pageview', options: [] },
        ]
        actions.map(action => {
            let format = { label: action.name, value: action.id }
            if (this.actionContains(action, '$autocapture')) data[0].options.push(format)
            if (this.actionContains(action, '$pageview')) data[2].options.push(format)
            if (!this.actionContains(action, '$autocapture') && !this.actionContains(action, '$pageview'))
                data[1].options.push(format)
        })
        return data
    }
    render() {
        let { action, actions, onClose, onChange, defaultMenuIsOpen } = this.props
        return (
            <div className="select-box">
                {action.id && (
                    <a href={'/action/' + action.id} target="_blank">
                        Edit "{action.name}" <i className="fi flaticon-export" />
                    </a>
                )}
                {this.state.infoOpen && (
                    <ActionSelectInfo
                        isOpen={this.state.infoOpen}
                        boundingRect={this.state.infoBoundingRect}
                        action={actions.filter(a => a.id == this.state.infoActionId)[0]}
                    />
                )}
                <Select
                    onBlur={e => {
                        if (e.relatedTarget && e.relatedTarget.tagName == 'A') return
                        this.setState({ infoOpen: false })
                        if (onClose) onClose()
                    }}
                    onChange={item => onChange(item.value)}
                    defaultMenuIsOpen={defaultMenuIsOpen}
                    autoFocus={true}
                    value={{
                        label: action.name,
                        value: action.id,
                    }}
                    className="select-box-select"
                    styles={selectStyle}
                    components={{ Option: this.Option }}
                    options={this.groupActions(actions)}
                />
            </div>
        )
    }
}
ActionSelectBox.propTypes = {
    onChange: PropTypes.func.isRequired,
    actions: PropTypes.array.isRequired,
    action: PropTypes.object.isRequired,
    onClose: PropTypes.func,
    defaultMenuIsOpen: PropTypes.bool,
}
