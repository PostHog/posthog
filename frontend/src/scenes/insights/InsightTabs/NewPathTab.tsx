import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { pathOptionsToProperty, pathsLogic, pathOptionsToLabels } from 'scenes/paths/pathsLogic'
import { Button, Checkbox, Col, Row, Select } from 'antd'
import { PropertyValue } from 'lib/components/PropertyFilters'
import { TestAccountFilter } from '../TestAccountFilter'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { PathType } from '~/types'
import './NewPathTab.scss'
import { GlobalFiltersTitle } from '../common'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { Popup } from 'lib/components/Popup/Popup'

import { PlusCircleOutlined } from '@ant-design/icons'

export function NewPathTab(): JSX.Element {
    const [visible, setVisible] = useState(false)
    const { customEventNames } = useValues(eventDefinitionsModel)
    const { filter } = useValues(pathsLogic({ dashboardItemId: null }))
    const { setFilter } = useActions(pathsLogic({ dashboardItemId: null }))

    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)

    return (
        <>
            <Row>
                <Col span={12}>
                    <Col className="event-types" style={{ paddingBottom: 16 }}>
                        <span style={{ paddingRight: 16 }}>Showing paths from</span>
                        <Row align="middle">
                            <Col span={3}> Events:</Col>
                            <Col span={7}>
                                <Checkbox /> Pageview events
                            </Col>
                            <Col span={7}>
                                <Checkbox /> Screenview events
                            </Col>
                            <Col span={7}>
                                <Checkbox /> Custom events
                            </Col>
                        </Row>
                        <Row align="middle">
                            <Col> Wildcard groups: (optional) </Col>
                            <Select
                                mode="tags"
                                style={{ width: '100%' }}
                                onChange={(val) => {
                                    console.log(val)
                                }}
                                tokenSeparators={[',', ' ']}
                             />
                        </Row>
                        <Row align="middle">
                            <Col span={9}>
                                <span>Starting at</span>
                            </Col>
                            <Col span={15}>
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
                        </Row>
                        <Row align="middle">
                            <Col span={9}>
                                <span>Ending at</span>
                            </Col>
                            <Col span={15}>
                                <Popup
                                    visible={visible}
                                    placement={'bottom-end'}
                                    fallbackPlacements={['bottom-start']}
                                    onClickOutside={() => setVisible(false)}
                                    overlay={
                                        <div className={`taxonomic-property-filter in-dropdown`}>
                                            <div className="taxonomic-filter-row">
                                                <Col>
                                                    <span>Event type:</span>
                                                </Col>
                                                <Col>
                                                    <Select
                                                        value={filter?.path_type || PathType.PageView}
                                                        defaultValue={PathType.PageView}
                                                        dropdownMatchSelectWidth={false}
                                                        onChange={(value): void =>
                                                            setFilter({ path_type: value, start_point: null })
                                                        }
                                                        style={{ paddingTop: 2 }}
                                                    >
                                                        {Object.entries(pathOptionsToLabels).map(
                                                            ([value, name], index) => {
                                                                return (
                                                                    <Select.Option key={index} value={value}>
                                                                        {name}
                                                                    </Select.Option>
                                                                )
                                                            }
                                                        )}
                                                    </Select>
                                                </Col>
                                                <Col>event:</Col>
                                                <Col>
                                                    <PropertyValue
                                                        outerOptions={
                                                            filter.path_type === PathType.CustomEvent
                                                                ? customEventNames.map((name) => ({
                                                                      name,
                                                                  }))
                                                                : undefined
                                                        }
                                                        onSet={(value: string | number): void =>
                                                            setFilter({ start_point: value })
                                                        }
                                                        propertyKey={
                                                            pathOptionsToProperty[filter.path_type || PathType.PageView]
                                                        }
                                                        type="event"
                                                        style={{ width: 200, paddingTop: 2 }}
                                                        value={filter.start_point}
                                                        placeholder={'Select start element'}
                                                        autoFocus={false}
                                                    />
                                                </Col>
                                            </div>
                                        </div>
                                    }
                                >
                                    {({ setRef }) => {
                                        return (
                                            <>
                                                <Button
                                                    ref={setRef}
                                                    onClick={() => setVisible(true)}
                                                    className="new-prop-filter"
                                                    data-attr={'new-prop-filter-' + 1}
                                                    type="link"
                                                    style={{ paddingLeft: 0 }}
                                                    icon={<PlusCircleOutlined />}
                                                >
                                                    Add end point
                                                </Button>
                                            </>
                                        )
                                    }}
                                </Popup>
                            </Col>
                        </Row>
                    </Col>
                </Col>
                <Col span={12} md={8} xs={24} style={{ marginTop: isSmallScreen ? '2rem' : 0, paddingLeft: 32 }}>
                    <GlobalFiltersTitle title={'Filters'} unit="actions/events" />
                    <PropertyFilters pageKey="insight-path" />
                    <TestAccountFilter filters={filter} onChange={setFilter} />
                </Col>
            </Row>
        </>
    )
}
