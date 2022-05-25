import React from 'react'
import { useValues, useActions } from 'kea'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { Button, Checkbox, Col, Row, Select } from 'antd'
import { InfoCircleOutlined, BarChartOutlined } from '@ant-design/icons'
import { PathType, FunnelPathType, AvailableFeature, PropertyGroupFilter } from '~/types'
import './PathTab.scss'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'

import { PathItemSelector } from 'lib/components/PropertyFilters/components/PathItemSelector'
import { PathItemFilters } from 'lib/components/PropertyFilters/PathItemFilters'
import { CloseButton } from 'lib/components/CloseButton'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Tooltip } from 'lib/components/Tooltip'
import { combineUrl, encodeParams, router } from 'kea-router'
import { insightLogic } from 'scenes/insights/insightLogic'
import { userLogic } from 'scenes/userLogic'
import { PayCard } from 'lib/components/PayCard/PayCard'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { groupsModel } from '~/models/groupsModel'
import { PathAdvanded } from './PathAdvanced'
import { PropertyGroupFilters } from 'lib/components/PropertyGroupFilters/PropertyGroupFilters'
import { convertPropertiesToPropertyGroup } from 'lib/utils'

export function PathTab(): JSX.Element {
    const { insightProps, allEventNames } = useValues(insightLogic)
    const { filter, wildcards } = useValues(pathsLogic(insightProps))
    const { setFilter, updateExclusions } = useActions(pathsLogic(insightProps))

    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const hasAdvancedPaths = user?.organization?.available_features?.includes(AvailableFeature.PATHS_ADVANCED)

    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)
    const taxonomicGroupTypes: TaxonomicFilterGroupType[] = filter.include_event_types
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

    const disablePageviewSelector =
        filter.include_event_types?.includes(PathType.PageView) && filter.include_event_types?.length === 1
    const disableScreenviewSelector =
        filter.include_event_types?.includes(PathType.Screen) && filter.include_event_types?.length === 1
    const disableCustomEventSelector =
        filter.include_event_types?.includes(PathType.CustomEvent) && filter.include_event_types?.length === 1

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
                                onClick={() => !disablePageviewSelector && onClickPathtype(PathType.PageView)}
                            >
                                <Checkbox
                                    checked={filter.include_event_types?.includes(PathType.PageView)}
                                    disabled={disablePageviewSelector}
                                    style={{
                                        pointerEvents: 'none',
                                    }}
                                >
                                    Page views
                                </Checkbox>
                            </Col>
                            <Col
                                xs={20}
                                sm={20}
                                xl={7}
                                className="tab-btn center ant-btn"
                                onClick={() => !disableScreenviewSelector && onClickPathtype(PathType.Screen)}
                            >
                                <Checkbox
                                    checked={filter.include_event_types?.includes(PathType.Screen)}
                                    disabled={disableScreenviewSelector}
                                    style={{
                                        pointerEvents: 'none',
                                    }}
                                >
                                    Screen views
                                </Checkbox>
                            </Col>
                            <Col
                                xs={20}
                                sm={20}
                                xl={7}
                                className="tab-btn right ant-btn"
                                onClick={() => !disableCustomEventSelector && onClickPathtype(PathType.CustomEvent)}
                            >
                                <Checkbox
                                    checked={filter.include_event_types?.includes(PathType.CustomEvent)}
                                    disabled={disableCustomEventSelector}
                                    style={{
                                        pointerEvents: 'none',
                                    }}
                                >
                                    Custom events
                                </Checkbox>
                            </Col>
                        </Row>
                        <hr />
                        {hasAdvancedPaths && (
                            <>
                                <Row align="middle">
                                    <Col>
                                        <b>Wildcard groups: (optional)</b>
                                        <Tooltip
                                            title={
                                                <>
                                                    Use wildcard matching to group events by unique values in path item
                                                    names. Use an asterisk (*) in place of unique values. For example,
                                                    instead of /merchant/1234/payment, replace the unique value with an
                                                    asterisk /merchant/*/payment.{' '}
                                                    <b>Use a comma to separate multiple wildcards.</b>
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
                            </>
                        )}
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
                                    taxonomicGroupTypes={taxonomicGroupTypes}
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
                        {hasAdvancedPaths && (
                            <>
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
                                            taxonomicGroupTypes={taxonomicGroupTypes}
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
                            </>
                        )}
                        {hasAdvancedPaths && (
                            <>
                                <hr />
                                <h4 className="secondary">Advanced options</h4>
                                <PathAdvanded />
                            </>
                        )}
                        {!hasAdvancedPaths && !preflight?.instance_preferences?.disable_paid_fs && (
                            <Row align="middle">
                                <Col span={24}>
                                    <PayCard
                                        identifier={AvailableFeature.PATHS_ADVANCED}
                                        title="Get a deeper understanding of your users"
                                        caption="Advanced features such as interconnection with funnels, grouping &amp; wildcarding and exclusions can help you gain deeper insights."
                                        docsLink="https://posthog.com/docs/user-guides/paths"
                                    />
                                </Col>
                            </Row>
                        )}
                    </Col>
                </Col>
                <Col span={12} style={{ marginTop: isSmallScreen ? '2rem' : 0, paddingLeft: 32 }}>
                    <PropertyGroupFilters
                        value={convertPropertiesToPropertyGroup(filter.properties)}
                        onChange={(properties: PropertyGroupFilter) => {
                            setFilter({ properties })
                        }}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            ...groupsTaxonomicTypes,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.Elements,
                        ]}
                        pageKey="insight-path"
                        eventNames={allEventNames}
                        filters={filter}
                        setTestFilters={(testFilters) => setFilter(testFilters)}
                    />
                    {hasAdvancedPaths && (
                        <>
                            <hr />
                            <h4 className="secondary">
                                Exclusions
                                <Tooltip
                                    title={
                                        <>
                                            Exclude events from Paths visualisation. You can use wildcard groups in
                                            exclusions as well.
                                        </>
                                    }
                                >
                                    <InfoCircleOutlined className="info-indicator" />
                                </Tooltip>
                            </h4>
                            <PathItemFilters
                                taxonomicGroupTypes={taxonomicGroupTypes}
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
                        </>
                    )}
                </Col>
            </Row>
        </>
    )
}
