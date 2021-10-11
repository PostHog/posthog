import React from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { pathOptionsToLabels, pathOptionsToProperty, pathsLogic } from 'scenes/paths/pathsLogic'
import { Col, Row, Select } from 'antd'
import { PropertyValue } from 'lib/components/PropertyFilters'
import { TestAccountFilter } from '../../TestAccountFilter'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { PathType } from '~/types'
import { GlobalFiltersTitle } from '../../common'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { NewPathTab } from './NewPathTab'
import { insightLogic } from 'scenes/insights/insightLogic'

export function PathTab(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.NEW_PATHS_UI] ? <NewPathTab /> : <OldPathTab />
}

export function OldPathTab(): JSX.Element {
    const { customEventNames } = useValues(eventDefinitionsModel)
    const { insightProps } = useValues(insightLogic)
    const { filter } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))

    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)

    return (
        <Row gutter={16}>
            <Col md={16} xs={24}>
                <Row gutter={8} align="middle" className="mt">
                    <Col>Showing paths from</Col>
                    <Col>
                        <Select
                            value={filter?.path_type || PathType.PageView}
                            defaultValue={PathType.PageView}
                            dropdownMatchSelectWidth={false}
                            onChange={(value): void => setFilter({ path_type: value, start_point: undefined })}
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
                    </Col>
                    <Col>starting at</Col>
                    <Col>
                        <PropertyValue
                            outerOptions={
                                filter.path_type === PathType.CustomEvent
                                    ? customEventNames.map((name) => ({
                                          name,
                                      }))
                                    : undefined
                            }
                            onSet={(value: string): void => setFilter({ start_point: value })}
                            propertyKey={pathOptionsToProperty[filter.path_type || PathType.PageView]}
                            type="event"
                            style={{ width: 200, paddingTop: 2 }}
                            value={filter.start_point}
                            placeholder={'Select start element'}
                            autoFocus={false}
                        />
                    </Col>
                </Row>
            </Col>
            <Col md={8} xs={24} style={{ marginTop: isSmallScreen ? '2rem' : 0 }}>
                <GlobalFiltersTitle unit="actions/events" />
                <PropertyFilters pageKey="insight-path" />
                <TestAccountFilter filters={filter} onChange={setFilter} />
            </Col>
        </Row>
    )
}
