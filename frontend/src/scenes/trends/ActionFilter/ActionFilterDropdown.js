import React, { useRef, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { EntityTypes } from '../trendsLogic'
import { ActionSelectPanel, ActionSelectTabs } from '~/lib/components/ActionSelectBox'
import { Link } from 'lib/components/Link'
import { userLogic } from 'scenes/userLogic'
import { actionsModel } from '~/models/actionsModel'

export function ActionFilterDropdown({ onClickOutside, logic }) {
    const dropdownRef = useRef()
    const { selectedFilter } = useValues(logic)
    const { eventNamesGrouped } = useValues(userLogic)
    const { actionsGrouped } = useValues(actionsModel)

    const deselect = e => {
        if (dropdownRef.current.contains(e.target)) {
            return
        }
        onClickOutside && onClickOutside(e)
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
                selected={selectedFilter.type && selectedFilter.type !== EntityTypes.NEW ? selectedFilter.type : null}
            >
                <ActionPanelContainer
                    title="actions"
                    entityType={EntityTypes.ACTIONS}
                    options={actionsGrouped}
                    panelIndex={0}
                    logic={logic}
                />
                <ActionPanelContainer
                    title="events"
                    entityType={EntityTypes.EVENTS}
                    options={eventNamesGrouped}
                    panelIndex={1}
                    logic={logic}
                />
            </ActionSelectTabs>
        </div>
    )
}

export function ActionPanelContainer({ entityType, panelIndex, options, logic }) {
    const { entities, selectedFilter, filters } = useValues(logic)
    const { updateFilter } = useActions(logic)

    const dropDownOnSelect = item => updateFilter({ type: entityType, value: item.value, index: selectedFilter.index })
    const dropDownOnHover = value => entities[entityType].filter(a => a.id === value)[0]

    const redirect = () => {
        if (selectedFilter && selectedFilter.type === EntityTypes.ACTIONS && entityType === EntityTypes.ACTIONS) {
            const action = entities[selectedFilter.type].filter(a => a.id === selectedFilter.filter.id)[0]
            return (
                <a href={'/action/' + selectedFilter.filter.id} target="_blank">
                    Edit "{action.name}" <i className="fi flaticon-export" />
                </a>
            )
        } else {
            return null
        }
    }

    const message = () => {
        if (entityType === EntityTypes.ACTIONS && !filters[EntityTypes.ACTIONS]) {
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
        />
    )
}
