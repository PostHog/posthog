import React, { useState } from 'react'
import { Card, CloseButton } from '../../lib/utils'
import { PropertyFilters } from '../../lib/components/PropertyFilters/PropertyFilters'
import Select from 'react-select'

import { actionsModel } from '~/models/actionsModel'
import { useValues } from 'kea'

function DayChoice({ days, name, group, onChange }) {
    return (
        <button
            onClick={() =>
                onChange({
                    action_id: group.action_id,
                    days,
                })
            }
            type="button"
            className={'btn btn-sm ' + (group.days == days ? 'btn-secondary' : 'btn-light')}
        >
            {name}
        </button>
    )
}

export function CohortGroup({ onChange, onRemove, group, index }) {
    const { actionsGrouped, actions } = useValues(actionsModel)
    const [selected, setSelected] = useState((group.action_id && 'action') || (group.properties && 'property'))

    return (
        <Card title={false} style={{ margin: 0 }}>
            <div className="card-body">
                {index > 0 && <CloseButton className="float-right" onClick={onRemove} />}
                <div style={{ height: 32 }}>
                    User has
                    {selected == 'action' && ' done '}
                    <div className="btn-group" style={{ margin: '0 8px' }}>
                        <button
                            onClick={() => setSelected('action')}
                            type="button"
                            className={'btn btn-sm ' + (selected == 'action' ? 'btn-secondary' : 'btn-light')}
                        >
                            action
                        </button>
                        <button
                            onClick={() => setSelected('property')}
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
                                <DayChoice days={1} name="day" group={group} onChange={onChange} />
                                <DayChoice days={7} name="7 days" group={group} onChange={onChange} />
                                <DayChoice days={30} name="month" group={group} onChange={onChange} />
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
                                    options={actionsGrouped}
                                    placeholder="Select action..."
                                    onChange={item => onChange({ action_id: item.value })}
                                    value={{
                                        label:
                                            actions.length > 0 &&
                                            group.action_id &&
                                            actions.filter(action => action.id == group.action_id)[0].name,
                                        value: group.action_id,
                                    }}
                                />
                            </div>
                        )}
                    </div>
                )}
            </div>
        </Card>
    )
}
