import React from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import {
    PAGEVIEW,
    AUTOCAPTURE,
    CUSTOM_EVENT,
    pathOptionsToLabels,
    pathOptionsToProperty,
    pathsLogic,
} from 'scenes/paths/pathsLogic'
import { Select } from 'antd'
import { userLogic } from 'scenes/userLogic'
import { PropertyValue } from 'lib/components/PropertyFilters'

export function PathTab(): JSX.Element {
    const { customEventNames } = useValues(userLogic)
    const { filter } = useValues(pathsLogic)
    const { setFilter } = useActions(pathsLogic)

    return (
        <>
            <h4 className="secondary">Path Type</h4>
            <Select
                value={filter?.type || PAGEVIEW}
                bordered={false}
                defaultValue={PAGEVIEW}
                dropdownMatchSelectWidth={false}
                onChange={(value): void => setFilter({ type: value, start: null })}
                style={{ paddingTop: 2 }}
            >
                {Object.entries(pathOptionsToLabels).map(([value, name], index) => {
                    return (
                        <Select.Option key={index} value={value}>
                            {name}
                        </Select.Option>
                    )
                })}
            </Select>
            <hr />
            <PropertyValue
                endpoint={filter?.type === AUTOCAPTURE && 'api/paths/elements'}
                outerOptions={
                    filter.type === CUSTOM_EVENT &&
                    customEventNames.map((name) => ({
                        name,
                    }))
                }
                onSet={(value): void => setFilter({ start: value })}
                propertyKey={pathOptionsToProperty[filter.type]}
                type="event"
                style={{ width: 200, paddingTop: 2 }}
                bordered={false}
                value={filter.start}
                placeholder={'Select start element'}
            ></PropertyValue>
            <hr />
            <h4 className="secondary">Filters</h4>
            <PropertyFilters pageKey="insight-path" />
        </>
    )
}
