import React, { Component, useState } from 'react'
import { ActionSelectInfo } from 'scenes/trends/ActionSelectInfo'
import PropTypes from 'prop-types'
import ActionSelectTab from './ActionSelectTab'
import { Select } from 'antd'

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
    constructor(props) {
        super(props)

        this.state = {
            infoOpen: false,
        }
    }

    determineValue = active => {
        if (active && active.filter && active.filter.type === this.props.title) return active.filter.id
        return null
    }

    render() {
        return (
            <div style={{ padding: '1rem', height: '90%', width: '100%' }} id="action-select-popup">
                {this.props.redirect}
                {this.state.infoOpen && (
                    <ActionSelectInfo
                        isOpen={this.state.infoOpen}
                        boundingRect={this.state.infoBoundingRect}
                        entity={this.props.onHover(this.state.infoActionId)}
                    />
                )}
                <Select
                    getPopupContainer={() => document.getElementById('action-select-popup')}
                    showSearch
                    defaultOpen
                    onChange={this.props.onSelect}
                    style={{ width: '100%' }}
                    filterOption={(input, option) =>
                        option.children &&
                        option.children.props.children.toLowerCase().indexOf(input.toLowerCase()) >= 0
                    }
                    value={this.determineValue(this.props.active)}
                    listHeight={300}
                >
                    {this.props.options.map(typeGroup => {
                        if (typeGroup['options'].length > 0) {
                            return (
                                <Select.OptGroup key={typeGroup['label']} label={typeGroup['label']}>
                                    {typeGroup['options'].map(item => (
                                        <Select.Option key={item.value} value={item.value}>
                                            <div
                                                onMouseOver={e =>
                                                    this.setState({
                                                        infoOpen: true,
                                                        infoBoundingRect: e.target.getBoundingClientRect(),
                                                        infoActionId: item.value,
                                                    })
                                                }
                                                onMouseOut={() => {
                                                    this.setState({ infoOpen: false })
                                                }}
                                            >
                                                {item.label}
                                            </div>
                                        </Select.Option>
                                    ))}
                                </Select.OptGroup>
                            )
                        }
                    })}
                </Select>
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
