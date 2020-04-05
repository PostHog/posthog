import React, { useRef, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { entityFilterLogic, EntityTypes } from './actionFilterLogic'
import { ActionSelectPanel, ActionSelectTabs } from '~/lib/components/ActionSelectBox'

export function ActionFilterDropdown(props) {
    const dropdownRef = useRef()
    const { formattedOptions, selectedFilter } = useValues(entityFilterLogic)

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
        <div ref={dropdownRef}>
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
                        ></ActionPanelContainer>
                    )
                })}
            </ActionSelectTabs>
        </div>
    )
}

export function ActionPanelContainer(props) {
    const { entityType, panelIndex, options } = props
    const { entities, selectedFilter } = useValues(entityFilterLogic)
    const { updateFilter } = useActions(entityFilterLogic)
    let dropDownOnSelect = item => updateFilter({ type: entityType, value: item.value, index: selectedFilter.index })
    let dropDownOnHover = value => entities[entityType].filter(a => a.id == value)[0]

    return (
        <ActionSelectPanel
            key={panelIndex}
            title={entityType}
            options={options}
            defaultMenuIsOpen={true}
            onSelect={dropDownOnSelect}
            onHover={dropDownOnHover}
            active={null}
        >
            {selectedFilter && selectedFilter.type == EntityTypes.ACTIONS && (
                <a href={'/action/' + selectedFilter.filter.id} target="_blank">
                    Edit "{selectedFilter.filter.name}" <i className="fi flaticon-export" />
                </a>
            )}
        </ActionSelectPanel>
    )
}
