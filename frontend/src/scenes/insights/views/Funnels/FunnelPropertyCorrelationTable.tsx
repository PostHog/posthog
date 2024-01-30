import './FunnelCorrelationTable.scss'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'
import { ConfigProvider, Empty, Table } from 'antd'
import Column from 'antd/lib/table/Column'
import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PropertySelect } from 'lib/components/PropertySelect/PropertySelect'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { VisibilitySensor } from 'lib/components/VisibilitySensor/VisibilitySensor'
import { IconSelectProperties, IconTrendingDown, IconTrendingUp } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { Popover } from 'lib/lemon-ui/Popover'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter } from 'lib/utils'
import { useEffect } from 'react'
import { useState } from 'react'
import { funnelCorrelationUsageLogic } from 'scenes/funnels/funnelCorrelationUsageLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelPersonsModalLogic } from 'scenes/funnels/funnelPersonsModalLogic'
import { funnelPropertyCorrelationLogic } from 'scenes/funnels/funnelPropertyCorrelationLogic'
import { parseDisplayNameForCorrelation } from 'scenes/funnels/funnelUtils'
import { ValueInspectorButton } from 'scenes/funnels/ValueInspectorButton'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelCorrelation, FunnelCorrelationResultsType, FunnelCorrelationType } from '~/types'

import { PropertyCorrelationActionsCell } from './CorrelationActionsCell'

export function FunnelPropertyCorrelationTable(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { steps, querySource, aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const {
        propertyCorrelationValues,
        propertyCorrelationTypes,
        propertyCorrelationsLoading,
        propertyNames,
        loadedPropertyCorrelationsTableOnce,
    } = useValues(funnelPropertyCorrelationLogic(insightProps))
    const { setPropertyCorrelationTypes, setPropertyNames, setAllProperties, loadPropertyCorrelations } = useActions(
        funnelPropertyCorrelationLogic(insightProps)
    )
    // Load correlations only if this component is mounted, and then reload if the query change
    useEffect(() => {
        // We only automatically refresh results when the query changes after the user has manually asked for the first results to be loaded
        if (loadedPropertyCorrelationsTableOnce) {
            loadPropertyCorrelations({})
        }
    }, [querySource])

    const { openCorrelationPersonsModal } = useActions(funnelPersonsModalLogic(insightProps))
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
                        <IconTrendingUp style={{ color: 'green' }} />
                    ) : (
                        <IconTrendingDown style={{ color: 'red' }} />
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
                    {querySource?.aggregation_group_type_index != undefined ? 'that' : 'who'} converted were{' '}
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
                <div className="funnel-correlation-header">
                    <div className="table-header">
                        <IconSelectProperties style={{ marginRight: 4, opacity: 0.5, fontSize: 24 }} />
                        CORRELATED PROPERTIES
                    </div>
                    <div className="table-options">
                        <div className="flex">
                            <p className="title">PROPERTIES</p>
                            <Popover
                                visible={isPropertiesOpen}
                                onClickOutside={() => setIsPropertiesOpen(false)}
                                overlay={
                                    <div className="p-4">
                                        <PropertySelect
                                            taxonomicFilterGroup={TaxonomicFilterGroupType.PersonProperties}
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
                                            <LemonButton size="small" type="primary" onClick={() => setAllProperties()}>
                                                Select all properties
                                            </LemonButton>
                                        )}
                                    </div>
                                }
                            >
                                <LemonButton size="small" onClick={() => setIsPropertiesOpen(true)}>
                                    {propertyNames.length === 1 && propertyNames[0] === '$all' ? (
                                        <>All properties selected</>
                                    ) : (
                                        <>
                                            {propertyNames.length} propert{propertyNames.length === 1 ? 'y' : 'ies'}{' '}
                                            selected
                                        </>
                                    )}
                                </LemonButton>
                            </Popover>
                        </div>
                        <div className="flex">
                            <p className="title ml-2">CORRELATION</p>
                            <div className="flex">
                                <LemonCheckbox
                                    checked={propertyCorrelationTypes.includes(FunnelCorrelationType.Success)}
                                    onChange={() => onClickCorrelationType(FunnelCorrelationType.Success)}
                                    label="Success"
                                    size="small"
                                    bordered
                                />
                                <LemonCheckbox
                                    checked={propertyCorrelationTypes.includes(FunnelCorrelationType.Failure)}
                                    onChange={() => onClickCorrelationType(FunnelCorrelationType.Failure)}
                                    label="Drop-off"
                                    size="small"
                                    bordered
                                />
                            </div>
                        </div>
                    </div>
                </div>
                <ConfigProvider
                    renderEmpty={() =>
                        loadedPropertyCorrelationsTableOnce ? (
                            <Empty />
                        ) : (
                            <>
                                {/* eslint-disable-next-line react/forbid-dom-props */}
                                <p className="m-auto" style={{ maxWidth: 500 }}>
                                    Highlight properties which are likely to have affected the conversion rate within
                                    the funnel.{' '}
                                    <Link to="https://posthog.com/manual/correlation">
                                        Learn more about correlation analysis.
                                    </Link>
                                </p>
                                <LemonButton
                                    type="secondary"
                                    onClick={() => setIsPropertiesOpen(true)}
                                    className="mx-auto mt-2"
                                >
                                    Select properties
                                </LemonButton>
                            </>
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
                                            querySource?.aggregation_group_type_index != undefined ? 'that' : 'who'
                                        } have this property and completed the entire funnel.`}
                                    >
                                        <IconInfo className="column-info" />
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
                                                {querySource?.aggregation_group_type_index != undefined
                                                    ? 'that'
                                                    : 'who'}{' '}
                                                have this property and did <b>not complete</b> the entire funnel.
                                            </>
                                        }
                                    >
                                        <IconInfo className="column-info" />
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
