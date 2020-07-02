import React, { useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import { EntityTypes } from '../trendsLogic'
import { CloseButton } from '~/lib/utils'
import { Dropdown } from '~/lib/components/Dropdown'
import { ActionFilterDropdown } from './ActionFilterDropdown'
import { Tooltip } from 'antd'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { userLogic } from 'scenes/userLogic'
import { DownOutlined, DragOutlined } from '@ant-design/icons'

const determineFilterLabel = (visible, filter) => {
    if (visible) return 'Hide Filters'

    if (filter.properties && Object.keys(filter.properties).length > 0) {
        return (
            Object.keys(filter.properties).length + ' Filter' + (Object.keys(filter.properties).length === 1 ? '' : 's')
        )
    }
    return 'Add Filters'
}

export function ActionFilterRow({ logic, filter, index, hideMathSelector }) {
    const node = useRef()
    const { selectedFilter, entities } = useValues(logic)
    const { selectFilter, updateFilterMath, removeLocalFilter, updateFilterProperty } = useActions(logic)
    const { eventProperties } = useValues(userLogic)
    const [entityFilterVisible, setEntityFilterVisible] = useState(false)

    let entity, name, value
    let math = filter.math
    const onClose = () => {
        removeLocalFilter({ value: filter.id, type: filter.type, index })
    }
    const onMathSelect = (_, math) => {
        updateFilterMath({ math, value: filter.id, type: filter.type, index: index })
    }

    const dropDownCondition = () =>
        selectedFilter && selectedFilter.type === filter.type && selectedFilter.index === index

    const onClick = () => {
        if (selectedFilter && selectedFilter.type === filter.type && selectedFilter.index === index) selectFilter(null)
        else selectFilter({ filter, type: filter.type, index })
    }

    if (filter.type === EntityTypes.NEW_ENTITY) {
        name = null
        value = null
    } else {
        entity = entities[filter.type].filter(action => action.id === filter.id)[0] || {}
        name = entity.name || filter.name
        value = entity.id || filter.id
    }
    return (
        <div className="action-filter-row mt-2">
            <DragOutlined className="action-filter-row-handle mr-2"/>
            <button
                data-attr={'trend-element-subject-' + index}
                ref={node}
                className="filter-action btn btn-sm btn-light"
                type="button"
                onClick={onClick}
                style={{
                    fontWeight: 500,
                }}
            >
                {name || 'Select action'}
                <DownOutlined style={{ marginLeft: '3px', color: 'rgba(0, 0, 0, 0.25)' }} />
            </button>
            {!hideMathSelector && <MathSelector math={math} index={index} onMathSelect={onMathSelect} />}
            <div
                className="btn btn-sm btn-light"
                onClick={() => setEntityFilterVisible(!entityFilterVisible)}
                data-attr={'show-prop-filter-' + index}
                style={{ marginLeft: 10, marginRight: 10 }}
            >
                {determineFilterLabel(entityFilterVisible, filter)}
            </div>
            <CloseButton
                onClick={onClose}
                style={{
                    float: 'none',
                    position: 'absolute',
                    marginTop: 3,
                }}
            />
            {entityFilterVisible && (
                <div className="ml-4">
                    <PropertyFilters
                        pageKey={`${index}-${value}-filter`}
                        properties={eventProperties}
                        propertyFilters={filter.properties}
                        onChange={properties => updateFilterProperty({ properties, index })}
                        style={{ marginBottom: 0 }}
                    />
                </div>
            )}
            {dropDownCondition() && (
                <ActionFilterDropdown
                    logic={logic}
                    onClickOutside={e => {
                        if (node.current.contains(e.target)) {
                            return
                        }
                        selectFilter(null)
                    }}
                />
            )}
        </div>
    )
}

function MathSelector(props) {
    let items = ['Total', 'DAU']
    return (
        <Dropdown
            title={items[items.map(i => i.toLowerCase()).indexOf(props.math)] || 'Total'}
            buttonClassName="btn btn-sm btn-light"
            style={{ marginLeft: 16 }}
            data-attr={'math-selector-' + props.index}
        >
            <Tooltip
                placement="right"
                title="Total shows total event volume. If a user performs an event 3 times on one day it counts as 3."
            >
                <a href="#" className="dropdown-item" onClick={() => props.onMathSelect(props.index, 'total')}>
                    Total
                </a>
            </Tooltip>

            <Tooltip
                placement="right"
                title="Daily Active Users. Selecting DAU will mean a user performing an event 3 times on one day counts as 1."
            >
                <a
                    href="#"
                    className="dropdown-item"
                    onClick={() => props.onMathSelect(props.index, 'dau')}
                    data-attr={'dau-option-' + props.index}
                >
                    DAU
                </a>
            </Tooltip>
        </Dropdown>
    )
}
