import React from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic, EntityTypes } from './actionFilterLogic'
import { CloseButton } from '~/lib/utils'
import { Dropdown } from '~/lib/components/Dropdown'
import { ActionFilterDropdown } from './ActionFilterDropdown'

export function ActionFilterRow(props) {
    const { filter, type, index } = props
    const { selectedFilter, entities, formattedFilters } = useValues(entityFilterLogic)
    const { selectFilter, setFilters, removeFilter } = useActions(entityFilterLogic)

    let entity, dropDownCondition, onClick, onClose, onMathSelect, name, value, math
    name = null
    value = null
    math = filter.math
    onClose = () => {
        removeFilter({ value: filter.id, type, index })
    }
    onMathSelect = (index, math) => {
        formattedFilters[type][index].math = math
        setFilters({ [type]: entities[type].filters })
    }

    dropDownCondition = () => selectedFilter && selectedFilter.type == type && selectedFilter.index == index

    onClick = () => {
        if (selectedFilter && selectedFilter.type == type && selectedFilter.index == index) selectFilter(null)
        else selectFilter({ filter, type, index })
    }

    if (type == EntityTypes.ACTIONS) {
        entity = entities[type].filter(action => action.id == filter.id)[0] || {}
        name = entity.name
        value = entity.id
    } else if (type == EntityTypes.EVENTS) {
        entity = entities[type].filter(event => event.name == filter.id)[0] || {}
        name = entity.name
        value = entity.name
    }

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
            {dropDownCondition() && <ActionFilterDropdown></ActionFilterDropdown>}
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
            <a href="#" className="dropdown-item" onClick={() => props.onMathSelect(props.index, 'total')}>
                Total
            </a>
            <a href="#" className="dropdown-item" onClick={() => props.onMathSelect(props.index, 'dau')}>
                DAU
            </a>
        </Dropdown>
    )
}
