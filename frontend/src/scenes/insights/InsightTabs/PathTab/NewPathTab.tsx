import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { Button, Checkbox, Col, Collapse, InputNumber, Row, Select } from 'antd'
import { InfoCircleOutlined, BarChartOutlined } from '@ant-design/icons'
import { TestAccountFilter } from '../../TestAccountFilter'
import { PathType, ViewType, FunnelPathType, PathEdgeParameters } from '~/types'
import './NewPathTab.scss'
import { GlobalFiltersTitle } from '../../common'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'

import { PathItemSelector } from 'lib/components/PropertyFilters/components/PathItemSelector'
import { PathItemFilters } from 'lib/components/PropertyFilters/PathItemFilters'
import { CloseButton } from 'lib/components/CloseButton'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Tooltip } from 'lib/components/Tooltip'
import { PersonModal } from 'scenes/trends/PersonModal'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { combineUrl, encodeParams, router } from 'kea-router'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'

export function NewPathTab(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filter, wildcards } = useValues(pathsLogic(insightProps))
    const { setFilter, updateExclusions } = useActions(pathsLogic(insightProps))

    const { showingPeople, cohortModalVisible } = useValues(personsModalLogic)
    const { setCohortModalVisible } = useActions(personsModalLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const [localEdgeParameters, setLocalEdgeParameters] = useState<PathEdgeParameters>({
        edge_limit: filter.edge_limit,
        min_edge_weight: filter.min_edge_weight,
        max_edge_weight: filter.max_edge_weight,
    })

    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)
    const groupTypes: TaxonomicFilterGroupType[] = filter.include_event_types
        ? [
              ...filter.include_event_types.map((item) => {
                  if (item === PathType.Screen) {
                      return TaxonomicFilterGroupType.Screens
                  } else if (item === PathType.CustomEvent) {
                      return TaxonomicFilterGroupType.CustomEvents
                  } else {
                      return TaxonomicFilterGroupType.PageviewUrls
                  }
              }),
              TaxonomicFilterGroupType.Wildcards,
          ]
        : [TaxonomicFilterGroupType.Wildcards]

    const overrideStartInput =
        filter.funnel_paths && [FunnelPathType.between, FunnelPathType.after].includes(filter.funnel_paths)
    const overrideEndInput =
        filter.funnel_paths && [FunnelPathType.between, FunnelPathType.before].includes(filter.funnel_paths)

    const updateEdgeParameters = (): void => {
        if (
            localEdgeParameters.edge_limit !== filter.edge_limit ||
            localEdgeParameters.min_edge_weight !== filter.min_edge_weight ||
            localEdgeParameters.max_edge_weight !== filter.max_edge_weight
        ) {
            setFilter({ ...localEdgeParameters })
        }
    }

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

    function _getStepNameAtIndex(filters: Record<string, any>, index: number): string {
        const targetEntity =
            filters.events?.filter((event: Record<string, any>) => {
                return event.order === index - 1
            })?.[0] ||
            filters.actions?.filter((action: Record<string, any>) => {
                return action.order === index - 1
            })?.[0]

        return targetEntity?.name || ''
    }

    function _getStepLabel(funnelFilters?: Record<string, any>, index?: number, shift: number = 0): JSX.Element {
        if (funnelFilters && index) {
            return (
                <div>
                    <BarChartOutlined />
                    <span className="label">{`${
                        index > 0 ? 'Funnel step ' + (index + shift) : 'Funnel dropoff ' + index * -1
                    }: ${_getStepNameAtIndex(funnelFilters, index > 0 ? index + shift : index * -1)}`}</span>
                </div>
            )
        } else {
            return <span />
        }
    }

    function getStartPointLabel(): JSX.Element {
        if (filter.funnel_paths) {
            if (filter.funnel_paths === FunnelPathType.after) {
                return _getStepLabel(filter.funnel_filter, filter.funnel_filter?.funnel_step)
            } else if (filter.funnel_paths === FunnelPathType.between) {
                // funnel_step targets the later of the 2 events when specifying between so the start point index is shifted back 1
                return _getStepLabel(filter.funnel_filter, filter.funnel_filter?.funnel_step, -1)
            } else {
                return <span />
            }
        } else {
            return filter.start_point ? (
                <span className="label">{filter.start_point}</span>
            ) : (
                <span className="label" style={{ color: 'var(--muted)' }}>
                    Add start point
                </span>
            )
        }
    }

    function getEndPointLabel(): JSX.Element {
        if (filter.funnel_paths) {
            if (filter.funnel_paths === FunnelPathType.before || filter.funnel_paths === FunnelPathType.between) {
                return _getStepLabel(filter.funnel_filter, filter.funnel_filter?.funnel_step)
            } else {
                return <span />
            }
        } else {
            return filter.end_point ? (
                <span className="label">{filter.end_point}</span>
            ) : (
                <span style={{ color: 'var(--muted)' }}>Add end point</span>
            )
        }
    }

    return (
        <>
            <PersonModal
                visible={showingPeople && !cohortModalVisible}
                view={ViewType.PATHS}
                filters={filter}
                onSaveCohort={() => {
                    setCohortModalVisible(true)
                }}
            />
            <Row>
                <Col span={12}>
                    <Col className="event-types" style={{ paddingBottom: 16 }}>
                        <Row align="middle">
                            <Col xs={20} sm={20} xl={3}>
                                <b>Events:</b>
                            </Col>
                            <Col
                                xs={20}
                                sm={20}
                                xl={7}
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
                                xs={20}
                                sm={20}
                                xl={7}
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
                                xs={20}
                                sm={20}
                                xl={7}
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
                                <Tooltip
                                    title={
                                        <>
                                            Use wildcard matching to group events by unique values in path item names.
                                            Use an asterisk (*) in place of unique values. For example, instead of
                                            /merchant/1234/payment, replace the unique value with an asterisk
                                            /merchant/*/payment. <b>Use a comma to separate multiple wildcards.</b>
                                        </>
                                    }
                                >
                                    <InfoCircleOutlined className="info-indicator" />
                                </Tooltip>
                            </Col>
                            <Select
                                mode="tags"
                                style={{ width: '100%', marginTop: 5 }}
                                onChange={(path_groupings) => setFilter({ path_groupings })}
                                tokenSeparators={[',']}
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
                                    disabled={overrideStartInput || overrideEndInput}
                                    wildcardOptions={wildcards}
                                >
                                    <Button
                                        data-attr={'new-prop-filter-' + 1}
                                        block={true}
                                        className="paths-endpoint-field"
                                        style={{
                                            textAlign: 'left',
                                            backgroundColor:
                                                overrideStartInput || overrideEndInput
                                                    ? 'var(--border-light)'
                                                    : 'white',
                                        }}
                                        disabled={overrideEndInput && !overrideStartInput}
                                        onClick={
                                            filter.funnel_filter && overrideStartInput
                                                ? () => {
                                                      router.actions.push(
                                                          combineUrl(
                                                              '/insights',
                                                              encodeParams(
                                                                  filter.funnel_filter as Record<string, any>,
                                                                  '?'
                                                              )
                                                          ).url
                                                      )
                                                  }
                                                : () => {}
                                        }
                                    >
                                        <div className="label-container">
                                            {getStartPointLabel()}
                                            {filter.start_point || overrideStartInput ? (
                                                <CloseButton
                                                    onClick={(e: Event) => {
                                                        setFilter({
                                                            start_point: undefined,
                                                            funnel_filter: undefined,
                                                            funnel_paths: undefined,
                                                        })
                                                        e.stopPropagation()
                                                    }}
                                                    className="close-button"
                                                />
                                            ) : null}
                                        </div>
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
                                    disabled={overrideEndInput || overrideStartInput}
                                    wildcardOptions={wildcards}
                                >
                                    <Button
                                        data-attr={'new-prop-filter-' + 0}
                                        block={true}
                                        className="paths-endpoint-field"
                                        style={{
                                            textAlign: 'left',
                                            backgroundColor:
                                                overrideStartInput || overrideEndInput
                                                    ? 'var(--border-light)'
                                                    : 'white',
                                        }}
                                        disabled={overrideStartInput && !overrideEndInput}
                                        onClick={
                                            filter.funnel_filter && overrideEndInput
                                                ? () => {
                                                      router.actions.push(
                                                          combineUrl(
                                                              '/insights',
                                                              encodeParams(
                                                                  filter.funnel_filter as Record<string, any>,
                                                                  '?'
                                                              )
                                                          ).url
                                                      )
                                                  }
                                                : () => {}
                                        }
                                    >
                                        <div className="label-container">
                                            {getEndPointLabel()}
                                            {filter.end_point || overrideEndInput ? (
                                                <CloseButton
                                                    onClick={(e: Event) => {
                                                        setFilter({
                                                            end_point: undefined,
                                                            funnel_filter: undefined,
                                                            funnel_paths: undefined,
                                                        })
                                                        e.stopPropagation()
                                                    }}
                                                    className="close-button"
                                                />
                                            ) : null}
                                        </div>
                                    </Button>
                                </PathItemSelector>
                            </Col>
                        </Row>
                        {featureFlags[FEATURE_FLAGS.NEW_PATHS_UI_EDGE_WEIGHTS] && (
                            <>
                                <hr />
                                <Row align="middle">
                                    <Col span={24}>
                                        <Collapse expandIconPosition="right">
                                            <Collapse.Panel header="Advanced Options" key="1">
                                                <Col>
                                                    <Row gutter={8} align="middle" className="mt-05">
                                                        <Col>Maximum number of Paths</Col>
                                                        <Col>
                                                            <InputNumber
                                                                style={{
                                                                    paddingTop: 2,
                                                                    width: '80px',
                                                                    marginLeft: 5,
                                                                    marginRight: 5,
                                                                }}
                                                                size="small"
                                                                min={0}
                                                                max={1000}
                                                                defaultValue={50}
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
                                                                style={{
                                                                    paddingTop: 2,
                                                                    width: '80px',
                                                                    marginLeft: 5,
                                                                    marginRight: 5,
                                                                }}
                                                                size="small"
                                                                min={0}
                                                                max={100000}
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
                                                                style={{
                                                                    paddingTop: 2,
                                                                    width: '80px',
                                                                    marginLeft: 5,
                                                                    marginRight: 5,
                                                                }}
                                                                size="small"
                                                                onChange={(value): void =>
                                                                    setLocalEdgeParameters((state) => ({
                                                                        ...state,
                                                                        max_edge_weight: Number(value),
                                                                    }))
                                                                }
                                                                min={0}
                                                                max={100000}
                                                                onBlur={updateEdgeParameters}
                                                                onPressEnter={updateEdgeParameters}
                                                            />
                                                        </Col>
                                                    </Row>
                                                </Col>
                                            </Collapse.Panel>
                                        </Collapse>
                                    </Col>
                                </Row>
                            </>
                        )}
                    </Col>
                </Col>
                <Col span={12} style={{ marginTop: isSmallScreen ? '2rem' : 0, paddingLeft: 32 }}>
                    <GlobalFiltersTitle title={'Filters'} unit="actions/events" />
                    <PropertyFilters pageKey="insight-path" />
                    <TestAccountFilter filters={filter} onChange={setFilter} />
                    <hr />
                    <h4 className="secondary">
                        Exclusions
                        <Tooltip
                            title={
                                <>
                                    Exclude events from Paths visualisation. You can use wildcard groups in exclusions
                                    as well.
                                </>
                            }
                        >
                            <InfoCircleOutlined className="info-indicator" />
                        </Tooltip>
                    </h4>
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
                        onChange={(values) => {
                            const exclusion = values.length > 0 ? values.map((v) => v.value) : values
                            updateExclusions(exclusion as string[])
                        }}
                        wildcardOptions={wildcards}
                    />
                </Col>
            </Row>
        </>
    )
}
