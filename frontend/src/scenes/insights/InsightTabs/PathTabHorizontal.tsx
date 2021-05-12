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
import { Col, Row, Select, Skeleton } from 'antd'
import { PropertyValue } from 'lib/components/PropertyFilters'
import { TestAccountFilter } from '../TestAccountFilter'
import { eventDefinitionsLogic } from 'scenes/events/eventDefinitionsLogic'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'

export function PathTabHorizontal(): JSX.Element {
    const { customEventNames } = useValues(eventDefinitionsLogic)
    const { filter, filtersLoading } = useValues(pathsLogic({ dashboardItemId: null }))
    const { setFilter } = useActions(pathsLogic({ dashboardItemId: null }))

    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)

    return (
        <Row gutter={16}>
            <Col md={16} xs={24}>
                <Row gutter={8} align="middle" className="mt">
                    <Col>Showing paths from</Col>
                    <Col>
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
                    </Col>
                    <Col>starting at</Col>
                    <Col>
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
                    </Col>
                </Row>
            </Col>
            <Col md={8} xs={24} style={{ marginTop: isSmallScreen ? '2rem' : 0 }}>
                <h4 className="secondary">Global Filters</h4>
                {filtersLoading ? (
                    <Skeleton active paragraph={{ rows: 1 }} />
                ) : (
                    <>
                        <PropertyFilters pageKey="insight-path" />
                        <TestAccountFilter filters={filter} onChange={setFilter} />
                    </>
                )}
            </Col>
        </Row>
    )
}
