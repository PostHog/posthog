import React, { useRef, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic } from './actionFilterLogic'
import { EntityTypes } from '../trendsLogic'
import { ActionSelectPanel, ActionSelectTabs } from '~/lib/components/ActionSelectBox'
import { Link } from 'react-router-dom'

export function ActionFilterDropdown(props) {
    const dropdownRef = useRef()
    const { formattedOptions, selectedFilter } = useValues(entityFilterLogic({ typeKey: props.typeKey }))

    const deselect = e => {
        if (dropdownRef.current.contains(e.target)) {
            return
        }
        props.onClickOutside ? props.onClickOutside(e) : null
    }

    useEffect(() => {
        document.addEventListener('mousedown', deselect)
        return () => {
            document.removeEventListener('mousedown', deselect)
        }
    }, [])

    return (
        <div ref={dropdownRef} className="action-filter-dropdown">
            <ActionSelectTabs
                selected={selectedFilter.type && selectedFilter.type != EntityTypes.NEW ? selectedFilter.type : null}
            >
                {Object.entries(formattedOptions).map((item, panelIndex) => {
                    let key = item[0]
                    let options = item[1]
                    return (
                        <ActionPanelContainer
                            key={panelIndex}
                            title={key}
                            entityType={key}
                            options={options}
                            panelIndex={panelIndex}
                            typeKey={props.typeKey}
                        ></ActionPanelContainer>
                    )
                })}
            </ActionSelectTabs>
        </div>
    )
}

export function ActionPanelContainer({ entityType, panelIndex, options, typeKey }) {
    const { entities, selectedFilter, filters } = useValues(entityFilterLogic({ typeKey }))
    const { updateFilter } = useActions(entityFilterLogic({ typeKey }))
    let dropDownOnSelect = item => updateFilter({ type: entityType, value: item.value, index: selectedFilter.index })
    let dropDownOnHover = value => entities[entityType].filter(a => a.id == value)[0]

    let redirect = () => {
        if (selectedFilter && selectedFilter.type == EntityTypes.ACTIONS) {
            let action = entities[selectedFilter.type].filter(a => a.id == selectedFilter.filter.id)[0]
            return (
                <a href={'/action/' + selectedFilter.filter.id} target="_blank">
                    Edit "{action.name}" <i className="fi flaticon-export" />
                </a>
            )
        } else {
            return null
        }
    }

    let message = () => {
        if (entityType == EntityTypes.ACTIONS && !filters[EntityTypes.ACTIONS]) {
            return (
                <div
                    style={{
                        height: '100%',
                        display: 'flex',
                        flexDirection: 'column',
                        justifyContent: 'center',
                        alignItems: 'center',
                    }}
                >
                    <p>You don't have any actions defined yet. </p>
                    <Link to="/action">Click here to define an action.</Link>
                </div>
            )
        } else {
            return null
        }
    }

    return (
        <ActionSelectPanel
            key={panelIndex}
            title={entityType}
            options={options}
            defaultMenuIsOpen={true}
            onSelect={dropDownOnSelect}
            onHover={dropDownOnHover}
            active={null}
            redirect={redirect()}
            message={message()}
        ></ActionSelectPanel>
    )
}
