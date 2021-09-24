import React from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { Button, Checkbox, Col, Row, Select } from 'antd'
import { TestAccountFilter } from '../TestAccountFilter'
import { PathType } from '~/types'
import './NewPathTab.scss'
import { GlobalFiltersTitle } from '../common'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'

import { PathItemSelector } from 'lib/components/PropertyFilters/components/PathItemSelector'
import { PathItemFilters } from 'lib/components/PropertyFilters/PathItemFilters'
import { CheckboxChangeEvent } from 'antd/lib/checkbox'

export function NewPathTab(): JSX.Element {
    const { filter } = useValues(pathsLogic({ dashboardItemId: null }))
    const { setFilter } = useActions(pathsLogic({ dashboardItemId: null }))

    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)

    const onChangeCheckbox = (e: CheckboxChangeEvent, pathType: PathType): void => {
        if (e.target.checked) {
            setFilter({
                include_event_types: filter.include_event_types
                    ? [...filter.include_event_types, pathType]
                    : [pathType],
            })
        } else {
            setFilter({
                include_event_types: filter.include_event_types
                    ? filter.include_event_types.filter((types) => types !== pathType)
                    : [],
            })
        }
    }

    return (
        <>
            <Row>
                <Col span={12}>
                    <Col className="event-types" style={{ paddingBottom: 16 }}>
                        <Row align="middle">
                            <Col span={3}>
                                <b>Events:</b>
                            </Col>
                            <Col span={7} className="ant-btn left">
                                <Checkbox
                                    checked={filter.include_event_types?.includes(PathType.PageView)}
                                    onChange={(e) => {
                                        onChangeCheckbox(e, PathType.PageView)
                                    }}
                                >
                                    Pageview events
                                </Checkbox>
                            </Col>
                            <Col span={7} className="ant-btn center">
                                <Checkbox
                                    checked={filter.include_event_types?.includes(PathType.Screen)}
                                    onChange={(e) => {
                                        onChangeCheckbox(e, PathType.Screen)
                                    }}
                                >
                                    Screenview events
                                </Checkbox>
                            </Col>
                            <Col span={7} className="ant-btn right">
                                <Checkbox
                                    checked={filter.include_event_types?.includes(PathType.CustomEvent)}
                                    onChange={(e) => {
                                        onChangeCheckbox(e, PathType.CustomEvent)
                                    }}
                                >
                                    Custom events
                                </Checkbox>
                            </Col>
                        </Row>
                        <hr />
                        <Row align="middle">
                            <Col>
                                <b>Wildcard groups: (optional)</b>
                            </Col>
                            <Select
                                mode="tags"
                                style={{ width: '100%', marginTop: 5 }}
                                onChange={(groupings) => setFilter({ groupings })}
                                tokenSeparators={[',', ' ']}
                                value={filter.groupings || []}
                            />
                        </Row>
                        <hr />
                        <Row align="middle">
                            <Col span={9}>
                                <b>Starting at</b>
                            </Col>
                            <Col span={15}>
                                <PathItemSelector
                                    pathItem={{
                                        type: filter.start_point_type || PathType.PageView,
                                        item: filter.start_point,
                                    }}
                                    index={0}
                                    onChange={(pathItem) =>
                                        setFilter({
                                            start_point: pathItem.item,
                                            start_point_type: pathItem.type,
                                        })
                                    }
                                >
                                    <Button
                                        data-attr={'new-prop-filter-' + 1}
                                        block={true}
                                        style={{
                                            maxWidth: '100%',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'space-between',
                                        }}
                                    >
                                        {filter.start_point && filter.start_point_type
                                            ? filter.start_point_type + ' ' + filter.start_point
                                            : 'Add start point'}
                                    </Button>
                                </PathItemSelector>
                            </Col>
                        </Row>
                        <hr />
                        <Row align="middle">
                            <Col span={9}>
                                <b>Ending at</b>
                            </Col>
                            <Col span={15}>
                                <PathItemSelector
                                    pathItem={{
                                        type: filter.end_point_type || PathType.PageView,
                                        item: filter.end_point,
                                    }}
                                    index={1}
                                    onChange={(pathItem) =>
                                        setFilter({
                                            end_point: pathItem.item,
                                            end_point_type: pathItem.type,
                                        })
                                    }
                                >
                                    <Button
                                        data-attr={'new-prop-filter-' + 0}
                                        block={true}
                                        style={{
                                            maxWidth: '100%',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'space-between',
                                        }}
                                    >
                                        {filter.end_point && filter.end_point_type
                                            ? filter.end_point_type + ' ' + filter.end_point
                                            : 'Add end point'}
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
                    <hr />
                    <GlobalFiltersTitle title={'Exclusion'} unit="actions/events" />
                    <PathItemFilters pageKey={'exclusion'} />
                </Col>
            </Row>
        </>
    )
}
