import React, { Component } from 'react'
import { Card, CloseButton } from '../../lib/utils'
import { PropertyFilters } from '../../lib/components/PropertyFilters/PropertyFilters'
import Select from 'react-select'

export class CohortGroup extends Component {
    constructor(props) {
        super(props)
        this.state = {
            days: 1,
            selected: (props.group.action_id && 'action') || (props.group.properties && 'property'),
        }
        this.DayChoice = this.DayChoice.bind(this)
    }
    DayChoice(props) {
        return (
            <button
                onClick={() =>
                    this.props.onChange({
                        action_id: this.props.group.action_id,
                        days: props.days,
                    })
                }
                type="button"
                className={'btn btn-sm ' + (this.props.group.days == props.days ? 'btn-secondary' : 'btn-light')}
            >
                {props.name}
            </button>
        )
    }
    render() {
        let { group, index, properties, actions, onChange, onRemove } = this.props
        let { selected } = this.state
        return (
            <Card title={false} style={{ margin: 0 }}>
                <div className="card-body">
                    {index > 0 && <CloseButton className="float-right" onClick={onRemove} />}
                    <div style={{ height: 32 }}>
                        User has
                        {selected == 'action' && ' done '}
                        <div className="btn-group" style={{ margin: '0 8px' }}>
                            <button
                                onClick={() => this.setState({ selected: 'action' })}
                                type="button"
                                className={'btn btn-sm ' + (selected == 'action' ? 'btn-secondary' : 'btn-light')}
                            >
                                action
                            </button>
                            <button
                                onClick={() => this.setState({ selected: 'property' })}
                                type="button"
                                className={'btn btn-sm ' + (selected == 'property' ? 'btn-secondary' : 'btn-light')}
                            >
                                property
                            </button>
                        </div>
                        {selected == 'action' && (
                            <span>
                                in the last
                                <div className="btn-group" style={{ margin: '0 8px' }}>
                                    <this.DayChoice days={1} name="day" />
                                    <this.DayChoice days={7} name="7 days" />
                                    <this.DayChoice days={30} name="month" />
                                </div>
                            </span>
                        )}
                    </div>
                    {selected && (
                        <div style={{ marginLeft: '2rem', minHeight: 38 }}>
                            {selected == 'property' && (
                                <PropertyFilters
                                    endpoint="person"
                                    pageKey="cohort"
                                    className=" "
                                    onChange={properties =>
                                        onChange({
                                            properties: properties,
                                            days: group.days,
                                        })
                                    }
                                    propertyFilters={group.properties || {}}
                                    style={{ margin: '1rem 0 0' }}
                                />
                            )}
                            {selected == 'action' && (
                                <div style={{ marginTop: '1rem', width: 350 }}>
                                    <Select
                                        options={actions}
                                        placeholder="Select action..."
                                        onChange={item => onChange({ action_id: item.value })}
                                        value={actions && actions.filter(action => action.value == group.action_id)}
                                    />
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </Card>
        )
    }
}
