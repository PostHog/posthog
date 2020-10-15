import React, { useState } from 'react'
import './ActionComponents.scss'
import { ActionSelectInfo } from 'scenes/insights/ActionSelectInfo'
import PropTypes from 'prop-types'
import { ActionSelectTab } from './ActionSelectTab'
import { Select } from 'antd'

const determineActiveTab = (props) => {
    if (props.selected) {
        return props.selected
    } else {
        return Array.isArray(props.children) ? props.children[0].props.entityType : props.children.props.entityType
    }
}

function ActionSelectTabs(props) {
    let [activeTab, setActiveTab] = useState(determineActiveTab(props))
    let [labels] = useState(
        Array.isArray(props.children)
            ? props.children.map((child) => child.props.entityType)
            : [props.children.props.entityType]
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
                ? props.children.map((child) => {
                      if (child.props.entityType !== activeTab) return undefined
                      return child
                  })
                : props.children}
        </div>
    )
}

function ActionSelectPanel({ title, redirect, onHover, onSelect, active, options, message, caption }) {
    const [infoOpen, setInfoOpen] = useState(false)
    const [infoBoundingRect, setInfoBoundingRect] = useState(null)
    const [infoActionId, setInfoActionId] = useState(null)

    function determineValue(active) {
        if (active && active.filter && active.filter.type === title) return active.filter.id
        return null
    }

    return (
        <div id="action-select-popup" className="as-popup">
            {redirect}
            {infoOpen && (
                <ActionSelectInfo isOpen={infoOpen} boundingRect={infoBoundingRect} entity={onHover(infoActionId)} />
            )}
            {caption && <div className="caption">{caption}</div>}
            <Select
                labelInValue
                getPopupContainer={() => document.getElementById('action-select-popup')}
                showSearch
                defaultOpen
                onChange={(option) => {
                    onSelect(option.value, option.label.props.children)
                }}
                style={{ width: '100%' }}
                filterOption={(input, option) =>
                    option.children && option.children.props.children?.toLowerCase().indexOf(input.toLowerCase()) >= 0
                }
                value={{ value: determineValue(active) }}
                listHeight={300}
            >
                {options.map((typeGroup) => {
                    if (typeGroup['options'].length > 0) {
                        return (
                            <Select.OptGroup key={typeGroup['label']} label={typeGroup['label']}>
                                {typeGroup['options'].map((item) => (
                                    <Select.Option key={item.value} value={item.value}>
                                        <div
                                            onMouseOver={(e) => {
                                                setInfoOpen(true)
                                                setInfoBoundingRect(e.target.getBoundingClientRect())
                                                setInfoActionId(item.value)
                                            }}
                                            onMouseOut={() => setInfoOpen(false)}
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
            {message}
        </div>
    )
}

ActionSelectPanel.propTypes = {
    options: PropTypes.array.isRequired,
    onSelect: PropTypes.func.isRequired,
    title: PropTypes.string.isRequired,
    onHover: PropTypes.func.isRequired,
}

export { ActionSelectPanel, ActionSelectTabs }
