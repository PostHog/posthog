import React, { useState } from 'react'
import { Row, Table } from 'antd'
import Column from 'antd/lib/table/Column'
import { useActions, useValues } from 'kea'
import { RiseOutlined, FallOutlined, EllipsisOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelCorrelation, FunnelCorrelationResultsType, FunnelCorrelationType } from '~/types'
import Checkbox from 'antd/lib/checkbox/Checkbox'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ValueInspectorButton } from 'scenes/funnels/FunnelBarGraph'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PropertyNamesSelect } from 'lib/components/PropertyNamesSelect/PropertyNamesSelect'
import { IconSelectProperties } from 'lib/components/icons'
import './FunnelCorrelationTable.scss'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { VisibilitySensor } from 'lib/components/VisibilitySensor/VisibilitySensor'
import { Popup } from 'lib/components/Popup/Popup'
import { LemonButton } from 'lib/components/LemonButton'
import { Tooltip } from 'lib/components/Tooltip'

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
        allProperties,
    } = useValues(logic)

    const { setPropertyCorrelationTypes, setPropertyNames, openCorrelationPersonsModal } = useActions(logic)

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

    const renderSuccessCount = (record: FunnelCorrelation): JSX.Element => {
        return (
            <ValueInspectorButton
                onClick={() => {
                    openCorrelationPersonsModal(record, true)
                }}
            >
                {record.success_count}
            </ValueInspectorButton>
        )
    }

    const renderFailureCount = (record: FunnelCorrelation): JSX.Element => {
        return (
            <ValueInspectorButton
                onClick={() => {
                    openCorrelationPersonsModal(record, false)
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
        <VisibilitySensor offset={150} id={`${correlationPropKey}-properties`}>
            <div className="funnel-correlation-table">
                <span className="funnel-correlation-header">
                    <span className="table-header">
                        <IconSelectProperties style={{ marginRight: 4, opacity: 0.5, fontSize: 24 }} />
                        CORRELATED PROPERTIES
                    </span>
                    <span className="table-options">
                        {allProperties.length > 0 && (
                            <>
                                <p className="title">PROPERTIES </p>
                                <PropertyNamesSelect
                                    value={new Set(propertyNames)}
                                    onChange={(selectedProperties: string[]) => setPropertyNames(selectedProperties)}
                                    allProperties={inversePropertyNames(excludedPropertyNames || [])}
                                />
                            </>
                        )}
                        <p className="title" style={{ marginLeft: 8 }}>
                            CORRELATION
                        </p>
                        <div
                            className="tab-btn ant-btn"
                            style={{
                                paddingTop: '1px',
                                paddingBottom: '1px',
                                borderTopRightRadius: 0,
                                borderBottomRightRadius: 0,
                            }}
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
                            style={{
                                marginRight: '8px',
                                paddingTop: '1px',
                                paddingBottom: '1px',
                                borderTopLeftRadius: 0,
                                borderBottomLeftRadius: 0,
                            }}
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
                >
                    <Column
                        title="Person property"
                        key="propertName"
                        render={(_, record: FunnelCorrelation) => renderOddsRatioTextRecord(record)}
                        align="left"
                    />
                    <Column
                        title={
                            <div className="flex-center">
                                Completed
                                <Tooltip title="Users who have this property and completed the entire funnel.">
                                    <InfoCircleOutlined className="column-info" />
                                </Tooltip>
                            </div>
                        }
                        key="success_count"
                        render={(_, record: FunnelCorrelation) => renderSuccessCount(record)}
                        width={90}
                        align="center"
                    />
                    <Column
                        title={
                            <div className="flex-center">
                                Dropped off
                                <Tooltip
                                    title={
                                        <>
                                            Users who have this property and did <b>not complete</b> the entire funnel.
                                        </>
                                    }
                                >
                                    <InfoCircleOutlined className="column-info" />
                                </Tooltip>
                            </div>
                        }
                        key="failure_count"
                        render={(_, record: FunnelCorrelation) => renderFailureCount(record)}
                        width={120}
                        align="center"
                    />
                    <Column
                        title=""
                        key="actions"
                        render={(_, record: FunnelCorrelation) => <CorrelationActionsCell record={record} />}
                        align="center"
                        width={30}
                    />
                </Table>
            </div>
        </VisibilitySensor>
    ) : null
}

const CorrelationActionsCell = ({ record }: { record: FunnelCorrelation }): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { excludePropertyFromProject, setFunnelCorrelationDetails } = useActions(logic)
    const { isPropertyExcludedFromProject } = useValues(logic)
    const propertyName = (record.event.event || '').split('::')[0]

    const [popoverOpen, setPopoverOpen] = useState(false)

    return (
        <Row style={{ justifyContent: 'flex-end' }}>
            <Popup
                visible={popoverOpen}
                actionable
                onClickOutside={() => setPopoverOpen(false)}
                overlay={
                    <>
                        <LemonButton onClick={() => setFunnelCorrelationDetails(record)} fullWidth type="stealth">
                            View correlation details
                        </LemonButton>
                        <LemonButton
                            disabled={isPropertyExcludedFromProject(propertyName)}
                            onClick={() => excludePropertyFromProject(propertyName)}
                            fullWidth
                            title="Remove this property from any correlation analysis report in this project."
                            type="stealth"
                        >
                            Exclude property from project
                        </LemonButton>
                    </>
                }
            >
                <LemonButton type="stealth" style={{ paddingLeft: 0 }} onClick={() => setPopoverOpen(!popoverOpen)}>
                    <EllipsisOutlined
                        style={{ color: 'var(--primary)', fontSize: 24 }}
                        className="insight-dropdown-actions"
                    />
                </LemonButton>
            </Popup>
        </Row>
    )
}
