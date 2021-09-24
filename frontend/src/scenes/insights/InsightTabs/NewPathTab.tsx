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

import { PlusCircleOutlined } from '@ant-design/icons'
import { PathItemSelector } from 'lib/components/PropertyFilters/components/PathItemSelector'
import { PathItemFilters } from 'lib/components/PropertyFilters/PathItemFilters'

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
                            <Col span={3}>
                                <b>Events:</b>
                            </Col>
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
                            <Col>
                                <b>Wildcard groups: (optional)</b>
                            </Col>
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
                                <b>Starting at</b>
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
                                <b>Ending at</b>
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
                    <hr />
                    <GlobalFiltersTitle title={'Exclusion'} unit="actions/events" />
                    <PathItemFilters pageKey={'exclusion'} />
                </Col>
            </Row>
        </>
    )
}
