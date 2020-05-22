import React, { useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import { EntityTypes } from '../trendsLogic'
import { CloseButton } from '~/lib/utils'
import { Dropdown } from '~/lib/components/Dropdown'
import { ActionFilterDropdown } from './ActionFilterDropdown'
import { Tooltip } from 'antd'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { userLogic } from 'scenes/userLogic'

const determineFilterLabel = (visible, filter) => {
    if (visible) return 'Hide Filters'

    if (filter.properties && Object.keys(filter.properties).length > 0) {
        return (
            Object.keys(filter.properties).length + ' Filter' + (Object.keys(filter.properties).length === 1 ? '' : 's')
        )
    }
    return 'Add Filters'
}

export function ActionFilterRow({ logic, filter, index }) {
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
        <div>
            <button
                data-attr={'trend-element-subject-' + index}
                ref={node}
                className="filter-action"
                type="button"
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
            <div className="btn btn-sm btn-light" onClick={() => setEntityFilterVisible(!entityFilterVisible)}>
                {determineFilterLabel(entityFilterVisible, filter)}
            </div>
            <CloseButton
                onClick={onClose}
                style={{
                    float: 'none',
                    marginLeft: 8,
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
            style={{ marginLeft: 32, marginRight: 16 }}
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
                <a href="#" className="dropdown-item" onClick={() => props.onMathSelect(props.index, 'dau')}>
                    DAU
                </a>
            </Tooltip>
        </Dropdown>
    )
}
