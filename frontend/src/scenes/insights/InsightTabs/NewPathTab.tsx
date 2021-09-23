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
                                <PathItemSelector
                                    pathItem={{ type: filter.path_type || PathType.PageView, item: filter.start_point }}
                                    index={0}
                                    onChange={() => {}}
                                >
                                    <Button
                                        className="new-prop-filter"
                                        data-attr={'new-prop-filter-' + 1}
                                        type="link"
                                        style={{ paddingLeft: 0 }}
                                        icon={<PlusCircleOutlined />}
                                    >
                                        Add start point
                                    </Button>
                                </PathItemSelector>
                            </Col>
                        </Row>
                        <Row align="middle">
                            <Col span={9}>
                                <span>Ending at</span>
                            </Col>
                            <Col span={15}>
                                <PathItemSelector
                                    pathItem={{ type: filter.path_type || PathType.PageView, item: filter.start_point }}
                                    index={1}
                                    onChange={() => {}}
                                >
                                    <Button
                                        className="new-prop-filter"
                                        data-attr={'new-prop-filter-' + 1}
                                        type="link"
                                        style={{ paddingLeft: 0 }}
                                        icon={<PlusCircleOutlined />}
                                    >
                                        Add end point
                                    </Button>
                                </PathItemSelector>
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

interface PathItem {
    type: PathType
    item: string | undefined
}

interface PathItemSelectorProps {
    pathItem: PathItem
    onChange: (item: PathItem) => void
    children: JSX.Element
    index: number
}

function PathItemSelector({ pathItem, onChange, children }: PathItemSelectorProps): JSX.Element {
    const { customEventNames } = useValues(eventDefinitionsModel)
    const [visible, setVisible] = useState(false)

    return (
        <Popup
            visible={visible}
            placement={'bottom-end'}
            fallbackPlacements={['bottom-start']}
            onClickOutside={() => setVisible(false)}
            overlay={
                <div className={`taxonomic-property-filter in-dropdown small`}>
                    <div className="taxonomic-filter-row">
                        <Col className={'taxonomic-where'}>
                            <span>Type:</span>
                        </Col>
                        <Col className={'taxonomic-button'}>
                            <Select
                                value={pathItem.type}
                                defaultValue={PathType.PageView}
                                dropdownMatchSelectWidth={false}
                                onChange={(value): void => onChange({ type: value, item: undefined })}
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
                        <Col className={'taxonomic-operator'}>event:</Col>
                        <Col className={'taxonomic-value-select'}>
                            <PropertyValue
                                outerOptions={
                                    pathItem.type === PathType.CustomEvent
                                        ? customEventNames.map((name) => ({
                                              name,
                                          }))
                                        : undefined
                                }
                                onSet={(value: string): void =>
                                    onChange({
                                        ...pathItem,
                                        item: value,
                                    })
                                }
                                propertyKey={pathOptionsToProperty[pathItem.type || PathType.PageView]}
                                type="event"
                                style={{ paddingTop: 2 }}
                                value={pathItem.item}
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
                    <div ref={setRef} onClick={() => setVisible(true)}>
                        {children}
                    </div>
                )
            }}
        </Popup>
    )
}
