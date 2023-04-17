import { useEffect } from 'react'
import { Link } from 'lib/lemon-ui/Link'
import { Col, ConfigProvider, Row, Table, Empty } from 'antd'
import Column from 'antd/lib/table/Column'
import { useActions, useValues } from 'kea'
import { RiseOutlined, FallOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import {
    FunnelCorrelation,
    FunnelCorrelationResultsType,
    FunnelCorrelationType,
    FunnelStepWithNestedBreakdown,
} from '~/types'
import Checkbox from 'antd/lib/checkbox/Checkbox'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ValueInspectorButton } from 'scenes/funnels/ValueInspectorButton'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { IconSelectProperties } from 'lib/lemon-ui/icons'
import './FunnelCorrelationTable.scss'
import { VisibilitySensor } from 'lib/components/VisibilitySensor/VisibilitySensor'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter } from 'lib/utils'
import { PropertyCorrelationActionsCell } from './CorrelationActionsCell'
import { funnelCorrelationUsageLogic } from 'scenes/funnels/funnelCorrelationUsageLogic'
import { parseDisplayNameForCorrelation } from 'scenes/funnels/funnelUtils'
import { funnelPropertyCorrelationLogic } from 'scenes/funnels/funnelPropertyCorrelationLogic'
import { Noun } from '~/models/groupsModel'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { Popover } from 'lib/lemon-ui/Popover'
import { PersonPropertySelect } from 'lib/components/PersonPropertySelect/PersonPropertySelect'
import { useState } from 'react'
import { LemonButton } from '@posthog/lemon-ui'

export function FunnelPropertyCorrelationTableDataExploration(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { steps, querySource, aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const { loadedPropertyCorrelationsTableOnce } = useValues(funnelPropertyCorrelationLogic(insightProps))
    const { loadPropertyCorrelations } = useActions(funnelPropertyCorrelationLogic(insightProps))

    // Load correlations only if this component is mounted, and then reload if the query change
    useEffect(() => {
        // We only automatically refresh results when the query changes after the user has manually asked for the first results to be loaded
        if (loadedPropertyCorrelationsTableOnce) {
            loadPropertyCorrelations({})
        }
    }, [querySource])

    return (
        <FunnelPropertyCorrelationTableComponent
            steps={steps}
            aggregation_group_type_index={querySource?.aggregation_group_type_index}
            aggregationTargetLabel={aggregationTargetLabel}
        />
    )
}

export function FunnelPropertyCorrelationTable(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { steps, filters, aggregationTargetLabel } = useValues(funnelLogic(insightProps))
    const { loadedPropertyCorrelationsTableOnce } = useValues(funnelPropertyCorrelationLogic(insightProps))
    const { loadPropertyCorrelations } = useActions(funnelPropertyCorrelationLogic(insightProps))

    // Load correlations only if this component is mounted, and then reload if filters change
    useEffect(() => {
        // We only automatically refresh results when filters change after the user has manually asked for the first results to be loaded
        if (loadedPropertyCorrelationsTableOnce) {
            loadPropertyCorrelations({})
        }
    }, [filters])

    return (
        <FunnelPropertyCorrelationTableComponent
            steps={steps}
            aggregation_group_type_index={filters?.aggregation_group_type_index}
            aggregationTargetLabel={aggregationTargetLabel}
        />
    )
}

type FunnelPropertyCorrelationTableComponentProps = {
    steps: FunnelStepWithNestedBreakdown[]
    aggregation_group_type_index?: number | undefined
    aggregationTargetLabel: Noun
}

export function FunnelPropertyCorrelationTableComponent({
    steps,
    aggregation_group_type_index,
    aggregationTargetLabel,
}: FunnelPropertyCorrelationTableComponentProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { openCorrelationPersonsModal } = useActions(funnelLogic(insightProps))
    const {
        propertyCorrelationValues,
        propertyCorrelationTypes,
        propertyCorrelationsLoading,
        propertyNames,
        loadedPropertyCorrelationsTableOnce,
    } = useValues(funnelPropertyCorrelationLogic(insightProps))
    const { setPropertyCorrelationTypes, setPropertyNames, setAllProperties } = useActions(
        funnelPropertyCorrelationLogic(insightProps)
    )
    const { correlationPropKey } = useValues(funnelCorrelationUsageLogic(insightProps))
    const { reportCorrelationInteraction } = useActions(funnelCorrelationUsageLogic(insightProps))
    const [isPropertiesOpen, setIsPropertiesOpen] = useState(false as boolean)

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
                    {capitalizeFirstLetter(aggregationTargetLabel.plural)}{' '}
                    {aggregation_group_type_index != undefined ? 'that' : 'who'} converted were{' '}
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

    return steps.length > 1 ? (
        <VisibilitySensor offset={150} id={`${correlationPropKey}-properties`}>
            <div className="funnel-correlation-table">
                <Row className="funnel-correlation-header">
                    <Col className="table-header">
                        <IconSelectProperties style={{ marginRight: 4, opacity: 0.5, fontSize: 24 }} />
                        CORRELATED PROPERTIES
                    </Col>
                    <Col className="table-options">
                        <Row style={{ display: 'contents' }}>
                            <>
                                <p className="title">PROPERTIES </p>
                                <Popover
                                    visible={isPropertiesOpen}
                                    onClickOutside={() => setIsPropertiesOpen(false)}
                                    overlay={
                                        <div className="p-4">
                                            <PersonPropertySelect
                                                onChange={setPropertyNames}
                                                selectedProperties={
                                                    propertyNames.length === 1 && propertyNames[0] === '$all'
                                                        ? []
                                                        : propertyNames
                                                }
                                                addText="Add properties"
                                            />
                                            <br />
                                            {propertyNames.length === 1 && propertyNames[0] === '$all' ? (
                                                <>All properties selected</>
                                            ) : (
                                                <LemonButton
                                                    size="small"
                                                    type="primary"
                                                    onClick={() => setAllProperties()}
                                                >
                                                    Select all properties
                                                </LemonButton>
                                            )}
                                        </div>
                                    }
                                >
                                    <LemonButton size="small" onClick={() => setIsPropertiesOpen(true)}>
                                        {propertyNames.length} propert{propertyNames.length === 1 ? 'y' : 'ies'}{' '}
                                        selected
                                    </LemonButton>
                                </Popover>
                            </>
                        </Row>
                        <Row style={{ display: 'contents' }}>
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
                                    Drop-off
                                </Checkbox>
                            </div>
                        </Row>
                    </Col>
                </Row>
                <ConfigProvider
                    renderEmpty={() =>
                        loadedPropertyCorrelationsTableOnce ? (
                            <Empty />
                        ) : (
                            <p style={{ margin: 'auto', maxWidth: 500 }}>
                                Correlated properties highlights properties users have that are likely to have affected
                                their conversion rate within the funnel.{' '}
                                <Link to="https://posthog.com/manual/correlation">
                                    Learn more about correlation analysis.
                                </Link>
                                <br />
                                <LemonButton
                                    type="secondary"
                                    onClick={() => setIsPropertiesOpen(true)}
                                    className="m-auto"
                                >
                                    Select properties
                                </LemonButton>
                            </p>
                        )
                    }
                >
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
                                reportCorrelationInteraction(
                                    FunnelCorrelationResultsType.Properties,
                                    'pagination change',
                                    {
                                        page,
                                        page_size,
                                    }
                                ),
                        }}
                    >
                        <Column
                            title={`${capitalizeFirstLetter(aggregationTargetLabel.singular)} property`}
                            key="propertName"
                            render={(_, record: FunnelCorrelation) => renderOddsRatioTextRecord(record)}
                            align="left"
                        />
                        <Column
                            title={
                                <div className="flex items-center">
                                    Completed
                                    <Tooltip
                                        title={`${capitalizeFirstLetter(aggregationTargetLabel.plural)} ${
                                            aggregation_group_type_index != undefined ? 'that' : 'who'
                                        } have this property and completed the entire funnel.`}
                                    >
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
                                <div className="flex items-center">
                                    Dropped off
                                    <Tooltip
                                        title={
                                            <>
                                                {capitalizeFirstLetter(aggregationTargetLabel.plural)}{' '}
                                                {aggregation_group_type_index != undefined ? 'that' : 'who'} have this
                                                property and did <b>not complete</b> the entire funnel.
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
                            render={(_, record: FunnelCorrelation) => (
                                <PropertyCorrelationActionsCell record={record} />
                            )}
                            align="center"
                            width={30}
                        />
                    </Table>
                </ConfigProvider>
            </div>
        </VisibilitySensor>
    ) : null
}
