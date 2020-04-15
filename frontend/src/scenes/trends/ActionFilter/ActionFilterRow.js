import React, { useRef } from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic } from './actionFilterLogic'
import { EntityTypes } from '../trendsLogic'
import { CloseButton } from '~/lib/utils'
import { Dropdown } from '~/lib/components/Dropdown'
import { ActionFilterDropdown } from './ActionFilterDropdown'

export function ActionFilterRow({ filter, index, showMaths, typeKey }) {
    const node = useRef()
    const { selectedFilter, entities } = useValues(entityFilterLogic({ typeKey }))
    const { selectFilter, updateFilterMath, removeLocalFilter } = useActions(entityFilterLogic({ typeKey }))

    let entity, dropDownCondition, onClick, onClose, onMathSelect, name, value, math
    math = filter.math
    onClose = () => {
        removeLocalFilter({ value: filter.id, type: filter.type, index })
    }
    onMathSelect = (_, math) => {
        updateFilterMath({ math, value: filter.id, type: filter.type, index: index })
    }

    dropDownCondition = () => selectedFilter && selectedFilter.type == filter.type && selectedFilter.index == index

    onClick = () => {
        if (selectedFilter && selectedFilter.type == filter.type && selectedFilter.index == index) selectFilter(null)
        else selectFilter({ filter, type: filter.type, index })
    }

    if (filter.type == EntityTypes.NEW) {
        name = null
        value = null
    } else {
        entity = entities[filter.type].filter(action => action.id == filter.id)[0] || {}
        name = entity.name
        value = entity.id
    }

    return (
        <div>
            <button
                ref={node}
                className="filter-action"
                type="button"
                onClick={onClick}
                type="button"
                style={{
                    border: 0,
                    padding: 0,
                    fontWeight: 500,
                    borderBottom: '1.5px dotted var(--blue)',
                }}
            >
                {name || 'Select action'}
            </button>
            {showMaths && <MathSelector math={math} index={index} onMathSelect={onMathSelect} />}
            <CloseButton
                onClick={onClose}
                style={{
                    float: 'none',
                    marginLeft: 8,
                    position: 'absolute',
                    marginTop: 3,
                }}
            />
            {dropDownCondition() && (
                <ActionFilterDropdown
                    typeKey={typeKey}
                    onClickOutside={e => {
                        if (node.current.contains(e.target)) {
                            return
                        }
                        selectFilter(null)
                    }}
                ></ActionFilterDropdown>
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
            <a href="#" className="dropdown-item" onClick={() => props.onMathSelect(props.index, 'total')}>
                Total
            </a>
            <a href="#" className="dropdown-item" onClick={() => props.onMathSelect(props.index, 'dau')}>
                DAU
            </a>
        </Dropdown>
    )
}
