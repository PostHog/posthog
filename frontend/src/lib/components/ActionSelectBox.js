import React, { Component, useState } from 'react'
import Select, { components } from 'react-select'
import { ActionSelectInfo } from '../../scenes/trends/ActionSelectInfo'
import { selectStyle } from '../utils'
import PropTypes from 'prop-types'
import ActionSelectTab from './ActionSelectTab'
import { Link } from 'react-router-dom'

const determineActiveTab = props => {
    if (props.selected) {
        return props.selected
    } else {
        return Array.isArray(props.children) ? props.children[0].props.title : props.children.props.title
    }
}

export function ActionSelectTabs(props) {
    let [activeTab, setActiveTab] = useState(determineActiveTab(props))
    let [labels] = useState(
        Array.isArray(props.children) ? props.children.map(child => child.props.title) : [props.children.props.title]
    )
    return (
        <div className="select-box" style={{ padding: 0 }}>
            {labels.length > 1 && (
                <ActionSelectTab
                    entityType={activeTab}
                    allTypes={labels}
                    chooseEntityType={setActiveTab}
                ></ActionSelectTab>
            )}
            {Array.isArray(props.children)
                ? props.children.map(child => {
                      if (child.props.title !== activeTab) return undefined
                      return child
                  })
                : props.children}
        </div>
    )
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
            <div style={{ padding: '1rem', height: '90%', width: '100%' }}>
                {this.props.redirect}
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
                    }}
                    onChange={this.props.onSelect}
                    defaultMenuIsOpen={this.props.defaultMenuIsOpen}
                    autoFocus={true}
                    value={this.props.active}
                    className="select-box-select"
                    styles={selectStyle}
                    components={{ Option: this.Option }}
                    options={this.props.options}
                />
                {this.props.message}
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
