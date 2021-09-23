import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { pathOptionsToProperty, pathsLogic } from 'scenes/paths/pathsLogic'
import { Button, Col, Row } from 'antd'
import { PropertyValue } from 'lib/components/PropertyFilters'
import { TestAccountFilter } from '../TestAccountFilter'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { PathType } from '~/types'
import './NewPathTab.scss'
import { GlobalFiltersTitle } from '../common'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Popup } from 'lib/components/Popup/Popup'
import { DownOutlined } from '@ant-design/icons'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

function PathEntityFilter({ type, visible }: { type: string; visible: boolean }): JSX.Element {
    return (
        <Popup
            overlay={
                <TaxonomicFilter
                    groupType={TaxonomicFilterGroupType.Events}
                    value={undefined}
                    onChange={() => {}}
                    onClose={() => {}}
                    groupTypes={[]}
                />
            }
            visible={visible}
            onClickOutside={() => {}}
        >
            {({ setRef }) => (
                <Button
                    data-attr={'paths-pageview-' + type}
                    onClick={() => {}}
                    block={true}
                    ref={setRef}
                    disabled={false}
                    style={{
                        maxWidth: '100%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                    }}
                >
                    <span className="text-overflow" style={{ maxWidth: '100%' }}>
                        <PropertyKeyInfo value={'Select'} disablePopover />
                    </span>
                    <DownOutlined style={{ fontSize: 10 }} />
                </Button>
            )}
        </Popup>
    )
}

export function NewPathTab(): JSX.Element {
    const [visible] = useState(false)
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
                            <Col span={9}>Pageview events</Col>
                            <Col span={15}>
                                <PathEntityFilter type={'pageview'} visible={visible} />
                            </Col>
                        </Row>
                        <Row align="middle">
                            <Col span={9}>Screenview events</Col>
                            <Col span={15}>
                                <PathEntityFilter type={'screenview'} visible={visible} />
                            </Col>
                        </Row>
                        <Row align="middle">
                            <Col span={9}>Custom events</Col>
                            <Col span={15}>
                                <PathEntityFilter type={'custom'} visible={visible} />
                            </Col>
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
                </Col>
                <Col span={12} md={8} xs={24} style={{ marginTop: isSmallScreen ? '2rem' : 0, paddingLeft: 32 }}>
                    <GlobalFiltersTitle unit="actions/events" />
                    <PropertyFilters pageKey="insight-path" />
                    <TestAccountFilter filters={filter} onChange={setFilter} />
                </Col>
            </Row>
        </>
    )
}
