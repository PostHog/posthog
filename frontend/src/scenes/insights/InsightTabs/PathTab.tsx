import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { pathOptionsToLabels, pathOptionsToProperty, pathsLogic } from 'scenes/paths/pathsLogic'
import { Col, InputNumber, Row, Select } from 'antd'
import { PropertyValue } from 'lib/components/PropertyFilters'
import { TestAccountFilter } from '../TestAccountFilter'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { PathEdgeParameters, PathType } from '~/types'
import { GlobalFiltersTitle } from '../common'

export function PathTab(): JSX.Element {
    const { customEventNames } = useValues(eventDefinitionsModel)
    const { filter } = useValues(pathsLogic({ dashboardItemId: null }))
    const { setFilter } = useActions(pathsLogic({ dashboardItemId: null }))
    const [localEdgeParameters, setLocalEdgeParameters] = useState<PathEdgeParameters>({
        edge_limit: filter.edge_limit,
        min_edge_weight: filter.min_edge_weight,
        max_edge_weight: filter.max_edge_weight,
    })
    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)

    const updateEdgeParameters = (): void => {
        if (
            localEdgeParameters.edge_limit !== filter.edge_limit ||
            localEdgeParameters.min_edge_weight !== filter.min_edge_weight ||
            localEdgeParameters.max_edge_weight !== filter.max_edge_weight
        ) {
            setFilter({ ...localEdgeParameters })
        }
    }
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
                        />
                    </Col>
                </Row>
                <Row gutter={8} align="middle" className="mt-05">
                    <Col>Maximum number of Paths</Col>
                    <Col>
                        <InputNumber
                            style={{ paddingTop: 2, width: '80px', marginLeft: 5, marginRight: 5 }}
                            size="small"
                            min={0}
                            max={1000}
                            defaultValue={100}
                            onChange={(value): void =>
                                setLocalEdgeParameters((state) => ({
                                    ...state,
                                    edge_limit: Number(value),
                                }))
                            }
                            onBlur={updateEdgeParameters}
                            onPressEnter={updateEdgeParameters}
                        />
                    </Col>
                </Row>
                <Row gutter={8} align="middle" className="mt-05">
                    <Col>Number of people on each Path between</Col>
                    <Col>
                        <InputNumber
                            style={{ paddingTop: 2, width: '80px', marginLeft: 5, marginRight: 5 }}
                            size="small"
                            onChange={(value): void =>
                                setLocalEdgeParameters((state) => ({
                                    ...state,
                                    min_edge_weight: Number(value),
                                }))
                            }
                            onBlur={updateEdgeParameters}
                            onPressEnter={updateEdgeParameters}
                        />
                    </Col>
                    <Col>and</Col>
                    <Col>
                        <InputNumber
                            style={{ paddingTop: 2, width: '80px', marginLeft: 5, marginRight: 5 }}
                            size="small"
                            onChange={(value): void =>
                                setLocalEdgeParameters((state) => ({
                                    ...state,
                                    max_edge_weight: Number(value),
                                }))
                            }
                            onBlur={updateEdgeParameters}
                            onPressEnter={updateEdgeParameters}
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
