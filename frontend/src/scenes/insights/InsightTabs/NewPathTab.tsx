import React from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { pathOptionsToProperty, pathsLogic } from 'scenes/paths/pathsLogic'
import { Button, Checkbox, Col, Collapse, Row, Skeleton } from 'antd'
import { PropertyValue } from 'lib/components/PropertyFilters'
import { TestAccountFilter } from '../TestAccountFilter'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { PathType } from '~/types'
import { PlusOutlined } from '@ant-design/icons'
import './NewPathTab.scss'
import { GlobalFiltersTitle } from '../common'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'

export function NewPathTab(): JSX.Element {
    const { customEventNames } = useValues(eventDefinitionsModel)
    const { filter, importantEvents, excludedEvents, results } = useValues(
        pathsLogic({ dashboardItemId: null })
    )
    const { setFilter, showPathEvents } = useActions(pathsLogic({ dashboardItemId: null }))

    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)

    return (
        <>
        <Row>

            <Col span={12}>
                <Col className="event-types" style={{ paddingBottom: 16 }}>
                    <span style={{ paddingRight: 16 }}>Showing paths from</span>
                    {/* <div> */}
                        <Row>
                            Page view events <Button></Button>
                        </Row>
                        <Row>
                            Screen view events <Button></Button>
                        </Row>
                        <Row>
                            Custom events
                        </Row>
                        <Row>
                            starting at
                        </Row>
                        <Row>
                            ending at 
                        </Row>
                    {/* </div> */}
                    {/* <Row style={{ border: 'none' }}>
                        <div style={{ borderRadius: '4px 0px 0px 4px', borderRight: 'none' }}>
                            <Checkbox defaultChecked={true} onChange={() => showPathEvents(PathType.PageView)}>
                                Page views <span className="text-muted">(web)</span>
                            </Checkbox>
                        </div>
                        <div style={{ borderRight: 'none' }}>
                            <Checkbox onChange={() => showPathEvents(PathType.Screen)}>
                                Screen views <span className="text-muted">(mobile)</span>
                            </Checkbox>
                        </div>
                        <div style={{ borderRadius: '0px 4px 4px 0px' }}>
                            <Checkbox onChange={() => showPathEvents(PathType.CustomEvent)}>Custom events</Checkbox>
                        </div>
                    </Row> */}
                </Col>
                <Row align="middle">
                    <Row>

                    </Row>
                    {/* <Col style={{ paddingRight: 8 }}> */}
                    <span>starting at</span>
                    {/* </Col> */}
                    <Col span={8} style={{ paddingRight: 8 }}>
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
                            value={filter.start_point}
                            placeholder={'Select start element'}
                            autoFocus={false}
                        />
                    </Col>
                    <Col style={{ paddingRight: 8 }}>
                        <span>and ending at</span>
                    </Col>
                    <Col span={8}>
                        <PropertyValue
                            outerOptions={
                                filter.path_type === PathType.CustomEvent
                                    ? customEventNames.map((name) => ({
                                        name,
                                    }))
                                    : undefined
                            }
                            onSet={(value: string | number): void => setFilter({ end_point: value })}
                            propertyKey={pathOptionsToProperty[filter.path_type || PathType.PageView]}
                            type="event"
                            value={filter.end_point}
                            placeholder={'Select end element'}
                            autoFocus={false}
                        />
                    </Col>
                </Row>
            </Col>
            {/* <Row className="path-filters"> */}
                {/* <Collapse
                    bordered={false}
                    expandIconPosition="right"
                    style={{
                        paddingLeft: 0,
                        width: '100%',
                        color: 'var(--primary-alt)',
                        background: 'none',
                        border: 'none',
                    }}
                > */}
                    {/* <Collapse.Panel
                        key="k"
                        header={
                            <Row align="middle">
                                Filters
                                <div style={{ flex: 1, marginLeft: 8, height: 1, background: 'var(--border)' }} />
                            </Row>
                        }
                        style={{ paddingLeft: 0, border: 'none' }}
                    > */}
            <Col span={12} md={8} xs={24} style={{ marginTop: isSmallScreen ? '2rem' : 0, paddingLeft: 32 }}>
                <GlobalFiltersTitle unit="actions/events" />
                <PropertyFilters pageKey="insight-path" />
                <TestAccountFilter filters={filter} onChange={setFilter} />
            </Col>
                    {/* </Collapse.Panel>
                </Collapse> */}
                {/* <Collapse
                    bordered={false}
                    expandIconPosition="right"
                    style={{
                        paddingLeft: 0,
                        width: '100%',
                        color: 'var(--primary-alt)',
                        background: 'none',
                        border: 'none',
                    }}
                > */}
                    {/* <Collapse.Panel
                        key="k"
                        header={
                            <Row align="middle">
                                Excluded events
                                <div style={{ flex: 1, marginLeft: 8, height: 1, background: 'var(--border)' }} />
                            </Row>
                        }
                        style={{ paddingLeft: 0, border: 'none' }}
                    > */}
                        {/* <Row className="text-muted mb">
                            Indicate which events you want to omit from the visualization
                        </Row>
                        <Row>
                            {excludedEvents.map((event) => (
                                <div key={event.source_id}>{event.name}</div>
                            ))}
                            <Button style={{ color: 'var(--primary)' }} icon={<PlusOutlined />}>
                                Add event
                            </Button>
                            {results.paths.map((p) => (
                                <div key={p.source_id}>{p.source}</div>
                            ))}
                        </Row> */}
                    {/* </Collapse.Panel>
                </Collapse> */}
                {/* <Collapse
                    bordered={false}
                    expandIconPosition="right"
                    style={{
                        paddingLeft: 0,
                        width: '100%',
                        color: 'var(--primary-alt)',
                        background: 'none',
                        border: 'none',
                    }}
                >
                    <Collapse.Panel
                        key="k"
                        header={
                            <Row align="middle">
                                Important events
                                <div style={{ flex: 1, marginLeft: 8, height: 1, background: 'var(--border)' }} />
                            </Row>
                        }
                        style={{ paddingLeft: 0, border: 'none' }}
                    >
                        <Row className="text-muted mb">
                            <span>
                                Important events are distinguished by color and are given priority when sorting and
                                aggregating path items
                            </span>
                        </Row>
                        <Row>
                            {importantEvents.map((event) => (
                                <div key={event.source_id}>{event.name}</div>
                            ))}
                            <Button style={{ color: 'var(--primary)' }} icon={<PlusOutlined />}>
                                Add event
                            </Button>
                        </Row>
                    </Collapse.Panel> */}
                {/* </Collapse> */}
            {/* </Row> */}
            </Row>

        </>
    )
}
