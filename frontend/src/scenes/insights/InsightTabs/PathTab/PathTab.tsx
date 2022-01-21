import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { Button, Checkbox, Col, Row, Select } from 'antd'
import { InfoCircleOutlined, BarChartOutlined } from '@ant-design/icons'
import { TestAccountFilter } from '../../TestAccountFilter'
import { PathType, InsightType, FunnelPathType, AvailableFeature } from '~/types'
import './PathTab.scss'
import { GlobalFiltersTitle } from '../../common'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'

import { PathItemSelector } from 'lib/components/PropertyFilters/components/PathItemSelector'
import { PathItemFilters } from 'lib/components/PropertyFilters/PathItemFilters'
import { CloseButton } from 'lib/components/CloseButton'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Tooltip } from 'lib/components/Tooltip'
import { PersonsModal } from 'scenes/trends/PersonsModal'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { combineUrl, encodeParams, router } from 'kea-router'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'
import { userLogic } from 'scenes/userLogic'
import { PayCard } from 'lib/components/PayCard/PayCard'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { groupsModel } from '~/models/groupsModel'
import { PathAdvanded } from './PathAdvanced'
import clsx from 'clsx'
import { IconArrowDropDown } from 'lib/components/icons'

export function PathTab(): JSX.Element {
    const { insightProps, allEventNames } = useValues(insightLogic)
    const { filter, wildcards } = useValues(pathsLogic(insightProps))
    const { setFilter, updateExclusions } = useActions(pathsLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    const [advancedOptionsShown, setAdvancedOptionShown] = useState(false) // TODO: Move to kea logic if option is kept

    const { showingPeople, cohortModalVisible } = useValues(personsModalLogic)
    const { setCohortModalVisible } = useActions(personsModalLogic)
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
            <PersonsModal
                visible={showingPeople && !cohortModalVisible}
                view={InsightType.PATHS}
                filters={filter}
                onSaveCohort={() => {
                    setCohortModalVisible(true)
                }}
                aggregationTargetLabel={{ singular: 'user', plural: 'users' }}
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
                                    Pageviews
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
                                    Screenviews
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
                        {['control', 'direct'].includes(
                            featureFlags[FEATURE_FLAGS.PATHS_ADVANCED_EXPERIMENT] as string
                        ) &&
                            hasAdvancedPaths && (
                                <>
                                    <hr />
                                    <h4
                                        className="secondary"
                                        style={{ display: 'flex', cursor: 'pointer', alignItems: 'center' }}
                                        onClick={() => setAdvancedOptionShown(!advancedOptionsShown)}
                                    >
                                        <span style={{ flexGrow: 1 }}>Advanced options</span>
                                        {featureFlags[FEATURE_FLAGS.PATHS_ADVANCED_EXPERIMENT] === 'control' && (
                                            <div
                                                className={clsx(
                                                    'advanced-options-dropdown',
                                                    advancedOptionsShown && 'expanded'
                                                )}
                                            >
                                                <IconArrowDropDown />
                                            </div>
                                        )}
                                    </h4>
                                    {featureFlags[FEATURE_FLAGS.PATHS_ADVANCED_EXPERIMENT] === 'direct' ||
                                    advancedOptionsShown ? (
                                        <PathAdvanded />
                                    ) : (
                                        <div
                                            className="text-muted-alt cursor-pointer"
                                            onClick={() => setAdvancedOptionShown(!advancedOptionsShown)}
                                        >
                                            Adjust maximum number of paths, path density or path cleaning options.
                                        </div>
                                    )}
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
                    <GlobalFiltersTitle title={'Filters'} unit="actions/events" />
                    <PropertyFilters
                        propertyFilters={filter.properties}
                        onChange={(properties) => setFilter({ properties })}
                        pageKey="insight-path"
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            ...groupsTaxonomicTypes,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.Elements,
                        ]}
                        eventNames={allEventNames}
                    />
                    <TestAccountFilter filters={filter} onChange={setFilter} />
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
