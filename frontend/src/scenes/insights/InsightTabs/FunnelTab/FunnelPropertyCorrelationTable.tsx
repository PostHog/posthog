import React from 'react'
import { Button, Table } from 'antd'
import Column from 'antd/lib/table/Column'
import { useActions, useValues } from 'kea'
import { RiseOutlined, FallOutlined } from '@ant-design/icons'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelCorrelation, FunnelCorrelationResultsType, FunnelCorrelationType, FunnelStep } from '~/types'
import Checkbox from 'antd/lib/checkbox/Checkbox'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ValueInspectorButton } from 'scenes/funnels/FunnelBarGraph'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PropertyNamesSelect } from 'lib/components/PropertyNamesSelect/PropertyNamesSelect'
import { IconSelectProperties } from 'lib/components/icons'
import './FunnelCorrelationTable.scss'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { VisibilitySensor } from 'lib/components/VisibilitySensor/VisibilitySensor'

export function FunnelPropertyCorrelationTable(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const {
        stepsWithCount,
        propertyCorrelationValues,
        propertyCorrelationTypes,
        excludedPropertyNames,
        parseDisplayNameForCorrelation,
        propertyCorrelationsLoading,
        inversePropertyNames,
        propertyNames,
        correlationPropKey,
    } = useValues(logic)

    const { setPropertyCorrelationTypes, openPersonsModal, setPropertyNames } = useActions(logic)

    const { reportCorrelationInteraction } = useActions(eventUsageLogic)

    const onClickCorrelationType = (correlationType: FunnelCorrelationType): void => {
        if (propertyCorrelationTypes) {
            if (propertyCorrelationTypes.includes(correlationType)) {
                setPropertyCorrelationTypes(propertyCorrelationTypes.filter((types) => types !== correlationType))
            } else {
                setPropertyCorrelationTypes([...propertyCorrelationTypes, correlationType])
            }
        } else {
            setPropertyCorrelationTypes([correlationType])
        }
    }

    const parseBreakdownValue = (item: string): { breakdown: string; breakdown_value: string } => {
        const components = item.split('::')
        if (components.length === 1) {
            return { breakdown: components[0], breakdown_value: '' }
        } else {
            return {
                breakdown: components[0],
                breakdown_value: components[1],
            }
        }
    }

    // A sentinel node used to respect typings
    const emptyFunnelStep: FunnelStep = {
        action_id: '',
        average_conversion_time: null,
        count: 0,
        name: '',
        order: 0,
        type: 'new_entity',
    }

    const renderSuccessCount = (record: FunnelCorrelation): JSX.Element => {
        const { breakdown, breakdown_value } = parseBreakdownValue(record.event.event || '')

        return (
            <ValueInspectorButton
                onClick={() => {
                    openPersonsModal(
                        { ...emptyFunnelStep, name: breakdown },
                        stepsWithCount.length,
                        breakdown_value,
                        breakdown,
                        'person',
                        [stepsWithCount.length] // funnel_custom_steps for correlations
                    )
                }}
            >
                {record.success_count}
            </ValueInspectorButton>
        )
    }

    const renderFailureCount = (record: FunnelCorrelation): JSX.Element => {
        const { breakdown, breakdown_value } = parseBreakdownValue(record.event.event || '')

        return (
            <ValueInspectorButton
                onClick={() => {
                    openPersonsModal(
                        { ...emptyFunnelStep, name: breakdown },
                        -2,
                        breakdown_value,
                        breakdown,
                        'person',
                        Array.from(Array(stepsWithCount.length).keys()).slice(1) // returns array like: [1,2,3,.... stepsWithCount.length - 1]
                    )
                }}
            >
                {record.failure_count}
            </ValueInspectorButton>
        )
    }

    const renderOddsRatioTextRecord = (record: FunnelCorrelation): JSX.Element => {
        const get_friendly_numeric_value = (value: number): string => {
            if (value < 10 && !Number.isInteger(value)) {
                return value.toFixed(1)
            }

            return value.toFixed()
        }

        const is_success = record.correlation_type === FunnelCorrelationType.Success

        const { first_value, second_value } = parseDisplayNameForCorrelation(record)

        return (
            <>
                <h4>
                    {is_success ? (
                        <RiseOutlined style={{ color: 'green' }} />
                    ) : (
                        <FallOutlined style={{ color: 'red' }} />
                    )}{' '}
                    <PropertyKeyInfo value={first_value} />
                    {second_value !== undefined && (
                        <>
                            {' :: '}
                            <PropertyKeyInfo value={second_value} disablePopover />
                        </>
                    )}
                </h4>
                <div>
                    People who converted were{' '}
                    <mark>
                        <b>
                            {get_friendly_numeric_value(record.odds_ratio)}x {is_success ? 'more' : 'less'} likely
                        </b>
                    </mark>{' '}
                    to have this property value
                </div>
            </>
        )
    }

    return stepsWithCount.length > 1 ? (
        <VisibilitySensor offset={300} id={`${correlationPropKey}-properties`}>
            <div className="funnel-correlation-table">
                <span className="funnel-correlation-header">
                    <span className="table-header">
                        <IconSelectProperties style={{ marginRight: 4, opacity: 0.5, fontSize: 24 }} />
                        CORRELATED PROPERTIES
                    </span>
                    <span className="table-options">
                        <p className="title">PROPERTIES </p>
                        <PropertyNamesSelect
                            value={new Set(propertyNames)}
                            onChange={(selectedProperties: string[]) => setPropertyNames(selectedProperties)}
                            allProperties={inversePropertyNames(excludedPropertyNames || [])}
                        />
                        <p className="title">CORRELATION</p>
                        <div
                            className="tab-btn ant-btn"
                            style={{ marginRight: '2px', paddingTop: '1px', paddingBottom: '1px' }}
                            onClick={() => onClickCorrelationType(FunnelCorrelationType.Success)}
                        >
                            <Checkbox
                                checked={propertyCorrelationTypes.includes(FunnelCorrelationType.Success)}
                                style={{
                                    pointerEvents: 'none',
                                }}
                            >
                                Success
                            </Checkbox>
                        </div>
                        <div
                            className="tab-btn ant-btn"
                            style={{ marginRight: '5px', paddingTop: '1px', paddingBottom: '1px' }}
                            onClick={() => onClickCorrelationType(FunnelCorrelationType.Failure)}
                        >
                            <Checkbox
                                checked={propertyCorrelationTypes.includes(FunnelCorrelationType.Failure)}
                                style={{
                                    pointerEvents: 'none',
                                }}
                            >
                                Dropoff
                            </Checkbox>
                        </div>
                    </span>
                </span>
                <Table
                    dataSource={propertyCorrelationValues}
                    loading={propertyCorrelationsLoading}
                    scroll={{ x: 'max-content' }}
                    size="small"
                    rowKey={(record: FunnelCorrelation) => record.event.event}
                    pagination={{
                        pageSize: 5,
                        hideOnSinglePage: true,
                        onChange: (page, page_size) =>
                            reportCorrelationInteraction(FunnelCorrelationResultsType.Properties, 'pagination change', {
                                page,
                                page_size,
                            }),
                    }}
                    style={{ marginTop: '1rem' }}
                >
                    <Column
                        title="Correlated Person Properties"
                        key="propertName"
                        render={(_, record: FunnelCorrelation) => renderOddsRatioTextRecord(record)}
                        align="left"
                        width="60%"
                    />
                    <Column
                        title="Completed"
                        key="success_count"
                        render={(_, record: FunnelCorrelation) => renderSuccessCount(record)}
                        width={90}
                        align="center"
                    />
                    <Column
                        title="Dropped off"
                        key="failure_count"
                        render={(_, record: FunnelCorrelation) => renderFailureCount(record)}
                        width={100}
                        align="center"
                    />
                    <Column
                        title="Actions"
                        key="actions"
                        render={(_, record: FunnelCorrelation) => <CorrelationActionsCell record={record} />}
                        align="center"
                    />
                </Table>
            </div>
        </VisibilitySensor>
    ) : null
}

const CorrelationActionsCell = ({ record }: { record: FunnelCorrelation }): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { excludePropertyFromProject } = useActions(logic)
    const { isPropertyExcludedFromProject } = useValues(logic)
    const propertyName = (record.event.event || '').split('::')[0]

    return (
        <Button
            disabled={isPropertyExcludedFromProject(propertyName)}
            onClick={() => excludePropertyFromProject(propertyName)}
            type="link"
        >
            Exclude
        </Button>
    )
}
