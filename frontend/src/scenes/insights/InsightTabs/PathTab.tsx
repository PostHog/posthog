import React from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { pathOptionsToLabels, pathOptionsToProperty, pathsLogic } from 'scenes/paths/pathsLogic'
import { Select } from 'antd'
import { PropertyValue } from 'lib/components/PropertyFilters'
import { TestAccountFilter } from '../TestAccountFilter'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PathTabHorizontal } from './PathTabHorizontal'
import { FEATURE_FLAGS } from 'lib/constants'
import { BaseTabProps } from '../Insights'
import { PathType } from '~/types'

export function PathTab(props: BaseTabProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.QUERY_UX_V2] ? <PathTabHorizontal {...props} /> : <DefaultPathTab />
}

function DefaultPathTab(): JSX.Element {
    const { customEventNames } = useValues(eventDefinitionsModel)
    const { filter } = useValues(pathsLogic({ dashboardItemId: null }))
    const { setFilter } = useActions(pathsLogic({ dashboardItemId: null }))

    return (
        <>
            <h4 className="secondary">Path Type</h4>
            <Select
                value={filter?.path_type || PathType.PageView}
                defaultValue={PathType.PageView}
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
                endpoint={filter.path_type === PathType.AutoCapture ? 'api/paths/elements' : undefined}
                outerOptions={
                    filter.path_type === PathType.CustomEvent
                        ? customEventNames.map((name) => ({
                              name,
                          }))
                        : undefined
                }
                onSet={(value: string | number): void => setFilter({ start_point: value })}
                propertyKey={pathOptionsToProperty[filter.path_type || PathType.PageView]}
                type="event"
                style={{ width: 200, paddingTop: 2 }}
                value={filter.start_point}
                placeholder={'Select start element'}
                autoFocus={false}
                allowCustom={filter.path_type !== PathType.AutoCapture}
            />
            <hr />
            <h4 className="secondary">Filters</h4>
            <PropertyFilters pageKey="insight-path" />
            <TestAccountFilter filters={filter} onChange={setFilter} />
        </>
    )
}
