import React, { Component } from 'react'
import { CloseButton, groupActions, groupEvents } from '../../lib/utils'
import { Dropdown } from '../../lib/components/Dropdown'
import { ActionSelectPanel, ActionSelectTabs } from '../../lib/components/ActionSelectBox'
import { Link } from 'react-router-dom'
import {EntityTypes} from './Trends'

export function ActionFilterRow(props) {
    let { math, index, name, dropDownCondition, onClick, onClose, onMathSelect } = props
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
            {dropDownCondition() && props.children}
        </div>
    )
}

export function MathSelector(props) {
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

export class ActionFilter extends Component {
    
    state = {
        newFilters: [],
    }

    _renderRow(filter, type, index) {
        let { entities } = this.props
        let { selected } = this.state

        let entity, dropDownCondition, onClick, onClose, onMathSelect, name, value, math, options, dropDownOnSelect, dropDownOnHover, active, redirect
        onClose = () => {
            entities[type].filters.splice(index, 1)
            this.props.onChange({[type]: entities[type].filters})
        }
        onMathSelect = (index, math) => {
            entities[type].filters[index].math = math
            this.props.onChange({[type]: entities[type].filters})
        }

        if(type == "new") {
            name = null
            value = null
            dropDownCondition= () => this.state.selected == type + index
            onClick = () => {
                if (selected == type + index) {
                    this.setState({
                        selected: null,
                    })
                } else {
                    this.setState({
                        selected: type + index,
                    })
                }
            }
            active = null
            redirect = null
            onClose = () => {
                let newfilters = this.state.newFilters.splice(index, 1)
                this.setState({
                    newfilters
                })
            }
        } else if(type == EntityTypes.ACTIONS) {
            entity = entities[type].data.filter(action => action.id == filter.id)[0] || {}
            dropDownCondition = () => this.state.selected == entity.id
            name = entity.name
            value = entity.id
            math = filter.math
            onClick = () => {
                if (selected == entity.id) {
                    this.setState({
                        selected: null,
                    })
                } else {
                    this.setState({
                        selected: entity.id,
                    })
                }
            }
            active = {
                label: entity.name,
                value: entity.id,
            }
            redirect = entity.id
        } else if(type == EntityTypes.EVENTS) {
            entity = entities[type].data.filter(event => event.name == filter.name)[0] || {}
            dropDownCondition = () => this.state.selected == entity.name
            name = entity.name
            value = entity.name
            math = filter.math
            onClick = () => {
                if (selected == entity.name) {
                    this.setState({
                        selected: null,
                    })
                } else {
                    this.setState({
                        selected: entity.name,
                    })
                }
            }
            active = {
                label: entity.name,
                value: entity.name,
            }
            redirect = false
        }
        return (
            <ActionFilterRow
                name={name}
                value={value}
                dropDownCondition={dropDownCondition}
                onClick={onClick}
                onClose={onClose}
                onMathSelect={onMathSelect}
                math={math}
                key={index}
                index={index}
            >
                <ActionSelectTabs>
                    {Object.entries(entities).map((item, panelIndex) => {
                        return this._renderPanels(type, item[0], index, item[1], panelIndex, active, redirect,)
                    })}
                </ActionSelectTabs>
            </ActionFilterRow>
        )
    }

    _renderPanels = (rowType, entityType, entityIndex, entities, panelIndex, active, redirect) => {
        let dropDownOnSelect, dropDownOnHover, options

        if(rowType == "new") {
            dropDownOnSelect = item => {
                entities.filters.push({ id: item.value })
                this.props.onChange({[entityType]: entities.filters})
            }
        } else {
            dropDownOnSelect = item => {
                entities.filters[panelIndex] = { id: item.value }
                this.props.onChange({[entityType]: entities.filters})
            }
            
        }
        dropDownOnHover = value => entities.data.filter(a => a.name == value)[0]

        if(entityType == EntityTypes.ACTIONS){
            options = groupActions(entities.data)
        } else if (entityType == EntityTypes.EVENTS){

            options = groupEvents(entities.data)
        }

        return (
            <ActionSelectPanel
                key={panelIndex}
                title={entityType}
                options={options}
                defaultMenuIsOpen={true}
                onSelect={dropDownOnSelect}
                onHover={dropDownOnHover}
                active={active}
            >
                {redirect && (
                    <a href={'/action/' + active.value} target="_blank">
                        Edit "{name}" <i className="fi flaticon-export" />
                    </a>
                )}
            </ActionSelectPanel>
        )

    }

    entitiesExist = () => {
        if (this.props.entities == null) {
            return false
        }
        Object.entries(this.props.entities).forEach((item, index) => {
            let val = item[1]
            if(Array.isArray(val.data)){
                return true
            }
        })
        return false
    }

    render() {
        let { newFilters } = this.state
        return !this.entitiesExist() ? (
            <div>
                {Object.entries(this.props.entities).map((item, index) => {
                    let key = item[0]
                    let val = item[1]
                    if(Array.isArray(val.filters) && Array.isArray(val.data)){
                        return val.filters.map((filter, index) => {
                            return this._renderRow(filter, key, index)
                        })
                    }
                })}
                {newFilters &&
                    newFilters.map((action_filter, index) => {
                        let filter = {}
                        return this._renderRow(filter, "new", index)
                    })}
                <button
                    className="btn btn-sm btn-outline-success"
                    onClick={() =>
                        this.setState({
                            newFilters: [...(newFilters || []), { id: -1 }],
                        })
                    }
                    style={{ marginTop: '0.5rem' }}
                >
                    Add action
                </button>
            </div>
        ) : (
            <div>
                You don't have any actions defined yet. <Link to="/action">Click here to define an action.</Link>
            </div>
        )
    }
}
