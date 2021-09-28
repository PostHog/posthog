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
import { CloseButton } from 'lib/components/CloseButton'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export function NewPathTab(): JSX.Element {
    const { filter } = useValues(pathsLogic({ dashboardItemId: null }))
    const { setFilter, updateExclusions } = useActions(pathsLogic({ dashboardItemId: null }))

    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)
    const groupTypes: TaxonomicFilterGroupType[] = filter.include_event_types
        ? filter.include_event_types.map((item) => {
              if (item === PathType.Screen) {
                  return TaxonomicFilterGroupType.Screens
              } else if (item === PathType.CustomEvent) {
                  return TaxonomicFilterGroupType.CustomEvents
              } else {
                  return TaxonomicFilterGroupType.PageviewUrls
              }
          })
        : []

    const onClickPathtype = (pathType: PathType): void => {
        if (filter.include_event_types) {
            if (filter.include_event_types.includes(pathType)) {
                setFilter({
                    include_event_types: filter.include_event_types.filter((types) => types !== pathType),
                })
            } else {
                setFilter({
                    include_event_types: filter.include_event_types
                        ? [...filter.include_event_types, pathType]
                        : [pathType],
                })
            }
        } else {
            setFilter({
                include_event_types: [pathType],
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
                            <Col
                                span={7}
                                className="tab-btn left ant-btn"
                                onClick={() => onClickPathtype(PathType.PageView)}
                            >
                                <Checkbox
                                    checked={filter.include_event_types?.includes(PathType.PageView)}
                                    style={{
                                        pointerEvents: 'none',
                                    }}
                                >
                                    Pageview events
                                </Checkbox>
                            </Col>
                            <Col
                                span={7}
                                className="tab-btn center ant-btn"
                                onClick={() => onClickPathtype(PathType.Screen)}
                            >
                                <Checkbox
                                    checked={filter.include_event_types?.includes(PathType.Screen)}
                                    style={{
                                        pointerEvents: 'none',
                                    }}
                                >
                                    Screenview events
                                </Checkbox>
                            </Col>
                            <Col
                                span={7}
                                className="tab-btn right ant-btn"
                                onClick={() => onClickPathtype(PathType.CustomEvent)}
                            >
                                <Checkbox
                                    checked={filter.include_event_types?.includes(PathType.CustomEvent)}
                                    style={{
                                        pointerEvents: 'none',
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
                                onChange={(path_groupings) => setFilter({ path_groupings })}
                                tokenSeparators={[',', ' ']}
                                value={filter.path_groupings || []}
                            />
                        </Row>
                        <hr />
                        <Row align="middle">
                            <Col span={9}>
                                <b>Starting at</b>
                            </Col>
                            <Col span={15}>
                                <PathItemSelector
                                    pathItem={filter.start_point}
                                    index={0}
                                    onChange={(pathItem) =>
                                        setFilter({
                                            start_point: pathItem,
                                        })
                                    }
                                    groupTypes={groupTypes}
                                >
                                    <Button
                                        data-attr={'new-prop-filter-' + 1}
                                        block={true}
                                        style={{
                                            maxWidth: '100%',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'space-between',
                                            overflow: 'hidden',
                                        }}
                                    >
                                        {filter.start_point ? (
                                            <>
                                                {filter.start_point}
                                                <CloseButton
                                                    onClick={(e: Event) => {
                                                        setFilter({ start_point: null })
                                                        e.stopPropagation()
                                                    }}
                                                    style={{
                                                        cursor: 'pointer',
                                                        float: 'none',
                                                        paddingLeft: 8,
                                                        alignSelf: 'center',
                                                    }}
                                                />
                                            </>
                                        ) : (
                                            <span style={{ color: 'var(--muted)' }}>Add start point</span>
                                        )}
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
                                    pathItem={filter.end_point}
                                    index={1}
                                    onChange={(pathItem) =>
                                        setFilter({
                                            end_point: pathItem,
                                        })
                                    }
                                    groupTypes={groupTypes}
                                >
                                    <Button
                                        data-attr={'new-prop-filter-' + 0}
                                        block={true}
                                        style={{
                                            maxWidth: '100%',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'space-between',
                                            overflow: 'hidden',
                                        }}
                                    >
                                        {filter.end_point ? (
                                            <>
                                                {filter.end_point}
                                                <CloseButton
                                                    onClick={(e: Event) => {
                                                        setFilter({ end_point: null })
                                                        e.stopPropagation()
                                                    }}
                                                    style={{
                                                        cursor: 'pointer',
                                                        float: 'none',
                                                        paddingLeft: 8,
                                                        alignSelf: 'center',
                                                    }}
                                                />
                                            </>
                                        ) : (
                                            <span style={{ color: 'var(--muted)' }}>Add end point</span>
                                        )}
                                    </Button>
                                </PathItemSelector>
                            </Col>
                        </Row>
                    </Col>
                </Col>
                <Col span={12} style={{ marginTop: isSmallScreen ? '2rem' : 0, paddingLeft: 32 }}>
                    <GlobalFiltersTitle title={'Filters'} unit="actions/events" />
                    <PropertyFilters pageKey="insight-path" />
                    <TestAccountFilter filters={filter} onChange={setFilter} />
                    <hr />
                    <GlobalFiltersTitle title={'Exclusion'} unit="actions/events" />
                    <PathItemFilters
                        groupTypes={groupTypes}
                        pageKey={'exclusion'}
                        propertyFilters={
                            filter.exclude_events &&
                            filter.exclude_events.map((name) => ({
                                key: name,
                                value: name,
                                operator: null,
                                type: 'event',
                            }))
                        }
                        onChange={updateExclusions}
                    />
                </Col>
            </Row>
        </>
    )
}
