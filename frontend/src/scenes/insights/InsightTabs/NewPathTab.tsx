import React from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { pathOptionsToLabels, pathOptionsToProperty, pathsLogic } from 'scenes/paths/pathsLogic'
import { Checkbox, Col, Collapse, Row, Select, Skeleton } from 'antd'
import { PropertyValue } from 'lib/components/PropertyFilters'
import { TestAccountFilter } from '../TestAccountFilter'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { BaseTabProps } from '../Insights'
import { InsightTitle } from './InsightTitle'
import { InsightActionBar } from './InsightActionBar'
import { PathType } from '~/types'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { GlobalFiltersTitle } from '../common'
import './NewPathTab.scss'

export function NewPathTab({ annotationsToCreate }: BaseTabProps): JSX.Element {
    const { customEventNames } = useValues(eventDefinitionsModel)
    const { filter, filtersLoading } = useValues(pathsLogic({ dashboardItemId: null }))
    const { setFilter } = useActions(pathsLogic({ dashboardItemId: null }))
    const { filledFilters: properties } = useValues(propertyFilterLogic({ pageKey: 'insight-path' }))

    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)

    const pathsEventTypes = [{name: 'Page views (web)'}]

    return (
        <>
        {/* // <Row> */}
            <Row align="middle" className="event-types" style={{paddingBottom: 16}}>
                <span style={{paddingRight: 16}}>Showing paths from</span>
                    <div style={{borderRadius: '4px 0px 0px 4px', borderRight: 'none'}}><Checkbox>Page views <span style={{color: 'var(--border-dark)'}}>(web)</span></Checkbox></div>
                    <div style={{borderRight: 'none' }}><Checkbox>Screen views <span style={{color: 'var(--border-dark)'}}>(mobile)</span></Checkbox></div>
                    <div style={{borderRight: 'none'}}><Checkbox>Autocaptured events</Checkbox></div>
                    <div style={{borderRadius: '0px 4px 4px 0px'}}><Checkbox>Custom events</Checkbox></div>
            </Row>
            <Row align="middle">
                <Col style={{paddingRight: 8}}><span>starting at</span></Col>
                <Col style={{paddingRight: 8}}>
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
                        value={filter.start_point}
                        placeholder={'Select start element'}
                        autoFocus={false}
                        allowCustom={filter.path_type !== PathType.AutoCapture}
                    />
                </Col>
                <Col style={{paddingRight: 8}}><span>and ending at</span></Col>
                <Col>
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
                        value={filter.start_point}
                        placeholder={'Select start element'}
                        autoFocus={false}
                        allowCustom={filter.path_type !== PathType.AutoCapture}
                    />
                </Col>
            </Row>
            <Row>
                <Collapse>
                    <Collapse.Panel key="k" header="Filters">
                        <GlobalFiltersTitle unit="actions/events" />
                        {filtersLoading ? (
                            <Skeleton active paragraph={{ rows: 1 }} />
                        ) : (
                            <>
                                <PropertyFilters pageKey="insight-path" />
                                <TestAccountFilter filters={filter} onChange={setFilter} />
                            </>
                        )}
                    </Collapse.Panel>
                </Collapse>
            </Row>
            {/* <Row gutter={24} style={{width: '100%'}}>
                <Col span={8}>
                    <Select
                        value={filter?.path_type || PathType.PageView}
                        defaultValue={PathType.PageView}
                        dropdownMatchSelectWidth={false}
                        style={{width: '100%'}}
                        onChange={(value): void => setFilter({ path_type: value, start_point: null })}
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
                <Col span={4}>
                    <Select
                        style={{width: '100%'}}
                        defaultValue="start" 
                    >
                        <Select.Option value="start">starting at</Select.Option>
                        <Select.Option value="end">ending at</Select.Option>
                    </Select>
                </Col>
                <Col span={12}>
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
                        value={filter.start_point}
                        placeholder={'Select start element'}
                        autoFocus={false}
                        allowCustom={filter.path_type !== PathType.AutoCapture}
                    />
                </Col>
            </Row> */}
            {/* <Row style={{ marginTop: isSmallScreen ? '2rem' : 0 }}>
                <GlobalFiltersTitle unit="actions/events" />
                {filtersLoading ? (
                    <Skeleton active paragraph={{ rows: 1 }} />
                ) : (
                    <>
                        <PropertyFilters pageKey="insight-path" />
                        <TestAccountFilter filters={filter} onChange={setFilter} />
                    </>
                )}
            </Row> */}
        {/* // </Row> */}
        </>
    )
}
