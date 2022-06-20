import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { ActionFilter } from '../../ActionFilter/ActionFilter'
import { Row, Checkbox, Col, Button } from 'antd'
import { BreakdownFilter } from '../../BreakdownFilter'
import { CloseButton } from 'lib/components/CloseButton'
import { InfoCircleOutlined, PlusCircleOutlined } from '@ant-design/icons'
import { trendsLogic } from '../../../trends/trendsLogic'
import { ChartDisplayType, FilterType, InsightType } from '~/types'
import { Formula } from './Formula'
import { TestAccountFilter } from 'scenes/insights/TestAccountFilter'
import './TrendTab.scss'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { GlobalFiltersTitle } from 'scenes/insights/common'
import { Tooltip } from 'lib/components/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { groupsModel } from '~/models/groupsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { alphabet, convertPropertiesToPropertyGroup } from 'lib/utils'
import { PropertyGroupFilters } from 'lib/components/PropertyGroupFilters/PropertyGroupFilters'
import { MathAvailability } from 'scenes/insights/ActionFilter/ActionFilterRow/ActionFilterRow'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export interface TrendTabProps {
    view: InsightType
}

export function TrendTab({ view }: TrendTabProps): JSX.Element {
    const { insightProps, allEventNames } = useValues(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { filters } = useValues(trendsLogic(insightProps))
    const { setFilters, toggleLifecycle } = useActions(trendsLogic(insightProps))
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const [isUsingFormulas, setIsUsingFormulas] = useState(filters.formula ? true : false)
    const lifecycles = [
        { name: 'new', tooltip: 'Users who were first seen on this period and did the activity during the period.' },
        { name: 'returning', tooltip: 'Users who did activity both this and previous period.' },
        {
            name: 'resurrecting',
            tooltip:
                'Users who did the activity this period but did not do the activity on the previous period (i.e. were inactive for 1 or more periods).',
        },
        {
            name: 'dormant',
            tooltip:
                'Users who went dormant on this period, i.e. users who did not do the activity this period but did the activity on the previous period.',
        },
    ]
    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)
    const isTrends = !filters.insight || filters.insight === InsightType.TRENDS
    const formulaAvailable = isTrends
    const formulaEnabled = (filters.events?.length || 0) + (filters.actions?.length || 0) > 0

    const propertiesTaxonomicGroupTypes = featureFlags[FEATURE_FLAGS.SESSION_ANALYSIS]
        ? [
              TaxonomicFilterGroupType.EventProperties,
              TaxonomicFilterGroupType.PersonProperties,
              TaxonomicFilterGroupType.Sessions,
              ...groupsTaxonomicTypes,
              TaxonomicFilterGroupType.Cohorts,
              TaxonomicFilterGroupType.Elements,
          ]
        : [
              TaxonomicFilterGroupType.EventProperties,
              TaxonomicFilterGroupType.PersonProperties,
              ...groupsTaxonomicTypes,
              TaxonomicFilterGroupType.Cohorts,
              TaxonomicFilterGroupType.Elements,
          ]

    return (
        <>
            <Row gutter={24}>
                <Col md={12} xs={24}>
                    {filters.insight === InsightType.LIFECYCLE ? (
                        <div className="mb-05">
                            Showing <b>Unique users</b> who did
                        </div>
                    ) : undefined}
                    <ActionFilter
                        filters={filters}
                        setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                        typeKey={`trends_${view}`}
                        buttonCopy="Add graph series"
                        showSeriesIndicator
                        entitiesLimit={
                            filters.insight === InsightType.LIFECYCLE || filters.display === ChartDisplayType.WorldMap
                                ? 1
                                : alphabet.length
                        }
                        mathAvailability={
                            filters.insight === InsightType.LIFECYCLE
                                ? MathAvailability.None
                                : filters.insight === InsightType.STICKINESS
                                ? MathAvailability.ActorsOnly
                                : MathAvailability.All
                        }
                        propertiesTaxonomicGroupTypes={propertiesTaxonomicGroupTypes}
                    />
                </Col>
                <Col md={12} xs={24} style={{ marginTop: isSmallScreen ? '2rem' : 0 }}>
                    {filters.insight === InsightType.LIFECYCLE && (
                        <>
                            <GlobalFiltersTitle unit="actions/events" />
                            <TestAccountFilter filters={filters} onChange={setFilters} />
                            <hr />
                            <h4 className="secondary">Lifecycle Toggles</h4>
                            <div className="toggles">
                                {lifecycles.map((lifecycle, idx) => (
                                    <div key={idx}>
                                        {lifecycle.name}{' '}
                                        <div>
                                            <Checkbox
                                                defaultChecked
                                                className={lifecycle.name}
                                                onChange={() => toggleLifecycle(lifecycle.name)}
                                            />
                                            <Tooltip title={lifecycle.tooltip}>
                                                <InfoCircleOutlined className="info-indicator" />
                                            </Tooltip>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </>
                    )}
                    {filters.insight !== InsightType.LIFECYCLE && (
                        <>
                            <PropertyGroupFilters
                                value={convertPropertiesToPropertyGroup(filters.properties)}
                                onChange={(properties) => {
                                    setFilters({ properties })
                                }}
                                taxonomicGroupTypes={propertiesTaxonomicGroupTypes}
                                pageKey="trends-filters"
                                eventNames={allEventNames}
                                filters={filters}
                                setTestFilters={(testFilters) => setFilters(testFilters)}
                            />

                            {formulaAvailable && (
                                <>
                                    <hr />
                                    <h4 className="secondary">
                                        Formula{' '}
                                        <Tooltip
                                            title={
                                                <>
                                                    Apply math operations to your series. You can do operations among
                                                    series (e.g. <code>A / B</code>) or simple arithmetic operations on
                                                    a single series (e.g. <code>A / 100</code>)
                                                </>
                                            }
                                        >
                                            <InfoCircleOutlined />
                                        </Tooltip>
                                    </h4>
                                    {isUsingFormulas ? (
                                        <Row align="middle" gutter={4}>
                                            <Col>
                                                <CloseButton
                                                    onClick={() => {
                                                        setIsUsingFormulas(false)
                                                        setFilters({ formula: undefined })
                                                    }}
                                                />
                                            </Col>
                                            <Col>
                                                <Formula
                                                    filters={filters}
                                                    onChange={(formula: string): void => {
                                                        setFilters({ formula })
                                                    }}
                                                    autoFocus
                                                    allowClear={false}
                                                />
                                            </Col>
                                        </Row>
                                    ) : (
                                        <Tooltip
                                            title={
                                                !formulaEnabled
                                                    ? 'Please add at least one graph series to use formulas'
                                                    : undefined
                                            }
                                            visible={formulaEnabled ? false : undefined}
                                        >
                                            <Button
                                                onClick={() => setIsUsingFormulas(true)}
                                                disabled={!formulaEnabled}
                                                type="link"
                                                style={{ paddingLeft: 0 }}
                                                icon={<PlusCircleOutlined />}
                                                data-attr="btn-add-formula"
                                            >
                                                Add formula
                                            </Button>
                                        </Tooltip>
                                    )}
                                </>
                            )}
                        </>
                    )}
                    {isTrends && (
                        <>
                            <hr />
                            <h4 className="secondary">
                                Breakdown by
                                <Tooltip
                                    placement="right"
                                    title="Use breakdown to see the aggregation (total volume, active users, etc.) for each value of that property. For example, breaking down by Current URL with total volume will give you the event volume for each URL your users have visited."
                                >
                                    <InfoCircleOutlined className="info-indicator" />
                                </Tooltip>
                            </h4>
                            <Row align="middle">
                                <BreakdownFilter filters={filters} setFilters={setFilters} />
                            </Row>
                        </>
                    )}
                </Col>
            </Row>
        </>
    )
}
