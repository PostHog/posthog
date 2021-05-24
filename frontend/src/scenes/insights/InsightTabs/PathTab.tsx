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
import { PropertyValue } from 'lib/components/PropertyFilters'
import { TestAccountFilter } from '../TestAccountFilter'
import { eventDefinitionsLogic } from 'scenes/events/eventDefinitionsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PathTabHorizontal } from './PathTabHorizontal'
import { FEATURE_FLAGS } from 'lib/constants'
import { BaseTabProps } from '../Insights'

export function PathTab(props: BaseTabProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.QUERY_UX_V2] ? <PathTabHorizontal {...props} /> : <DefaultPathTab />
}

function DefaultPathTab(): JSX.Element {
    const { customEventNames } = useValues(eventDefinitionsLogic)
    const { filter } = useValues(pathsLogic({ dashboardItemId: null }))
    const { setFilter } = useActions(pathsLogic({ dashboardItemId: null }))

    return (
        <>
            <h4 className="secondary">Path Type</h4>
            <Select
                value={filter?.path_type || PAGEVIEW}
                defaultValue={PAGEVIEW}
                dropdownMatchSelectWidth={false}
                onChange={(value): void => setFilter({ path_type: value, start_point: null })}
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
            <h4 className="secondary">Start Point</h4>
            <PropertyValue
                endpoint={filter.path_type === AUTOCAPTURE && 'api/paths/elements'}
                outerOptions={
                    filter.path_type === CUSTOM_EVENT &&
                    customEventNames.map((name) => ({
                        name,
                    }))
                }
                onSet={(value: string | number): void => setFilter({ start_point: value })}
                propertyKey={pathOptionsToProperty[filter.path_type || PAGEVIEW]}
                type="event"
                style={{ width: 200, paddingTop: 2 }}
                value={filter.start_point}
                placeholder={'Select start element'}
                operator={null}
            />
            <hr />
            <h4 className="secondary">Filters</h4>
            <PropertyFilters pageKey="insight-path" />
            <TestAccountFilter filters={filter} onChange={setFilter} />
        </>
    )
}
