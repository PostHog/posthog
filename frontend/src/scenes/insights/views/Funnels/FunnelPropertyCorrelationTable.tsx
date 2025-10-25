import './FunnelCorrelationTable.scss'

import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { useState } from 'react'

import { IconArchive, IconTrending } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonTable } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PropertySelect } from 'lib/components/PropertySelect/PropertySelect'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { VisibilitySensor } from 'lib/components/VisibilitySensor/VisibilitySensor'
import { Link } from 'lib/lemon-ui/Link'
import { Popover } from 'lib/lemon-ui/Popover'
import { IconSelectProperties, IconTrendingDown } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter } from 'lib/utils'
import { ValueInspectorButton } from 'scenes/funnels/ValueInspectorButton'
import { funnelCorrelationUsageLogic } from 'scenes/funnels/funnelCorrelationUsageLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelPersonsModalLogic } from 'scenes/funnels/funnelPersonsModalLogic'
import { funnelPropertyCorrelationLogic } from 'scenes/funnels/funnelPropertyCorrelationLogic'
import { parseDisplayNameForCorrelation } from 'scenes/funnels/funnelUtils'
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
    }, [querySource]) // oxlint-disable-line react-hooks/exhaustive-deps

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
                <div className="font-semibold text-text-3000">
                    {is_success ? (
                        <IconTrending style={{ color: 'green' }} />
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
                </div>
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
            <div className="FunnelCorrelationTable mt-4 border rounded overflow-hidden">
                <div className="flex px-2 py-1 bg-[var(--color-bg-table)]">
                    <div className="flex items-center text-xs font-bold">
                        <IconSelectProperties style={{ marginRight: 4, opacity: 0.5, fontSize: 24 }} />
                        CORRELATED PROPERTIES
                    </div>
                    <div className="table-options flex grow items-center justify-end flex-wrap">
                        <div className="flex">
                            <p className="flex items-center m-1 font-sans text-xs text-secondary font-semibold">
                                PROPERTIES
                            </p>
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
                                            <LemonButton
                                                size="small"
                                                type="primary"
                                                onClick={() => {
                                                    setAllProperties()
                                                    setIsPropertiesOpen(false)
                                                }}
                                            >
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
                            <p className="flex items-center m-1 font-sans text-xs text-secondary font-semibold ml-2">
                                CORRELATION
                            </p>
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

                <LemonTable
                    id="property-correlation"
                    embedded
                    columns={[
                        {
                            title: `${capitalizeFirstLetter(aggregationTargetLabel.singular)} property`,
                            key: 'propertName',
                            render: (_, record) => renderOddsRatioTextRecord(record),
                        },
                        {
                            title: 'Completed',
                            tooltip: `${capitalizeFirstLetter(aggregationTargetLabel.plural)} ${
                                querySource?.aggregation_group_type_index != undefined ? 'that' : 'who'
                            } have this property and completed the entire funnel.`,
                            key: 'success_count',
                            render: (_, record) => renderSuccessCount(record),
                            width: 90,
                            align: 'center',
                        },
                        {
                            title: 'Dropped off',
                            tooltip: `${capitalizeFirstLetter(aggregationTargetLabel.plural)} ${
                                querySource?.aggregation_group_type_index != undefined ? 'that' : 'who'
                            } have this property and did not complete the entire funnel.`,
                            key: 'failure_count',
                            render: (_, record) => renderFailureCount(record),
                            width: 120,
                            align: 'center',
                        },
                        {
                            key: 'actions',
                            width: 30,
                            align: 'center',
                            render: (_, record) => <PropertyCorrelationActionsCell record={record} />,
                        },
                    ]}
                    dataSource={propertyCorrelationValues}
                    loading={propertyCorrelationsLoading}
                    rowKey={(record) => record.event.event}
                    size="small"
                    emptyState={
                        <div className="p-4 m-auto max-w-140">
                            <div className="flex flex-col items-center justify-self-center text-center">
                                {loadedPropertyCorrelationsTableOnce ? (
                                    <div className="flex flex-col items-center justify-center deprecated-space-y-1 min-h-24">
                                        <IconArchive className="text-tertiary-hover text-2xl" />
                                        <div>No correlated properties found.</div>
                                    </div>
                                ) : (
                                    <>
                                        <p className="m-auto">
                                            Highlight properties which are likely to have affected the conversion rate
                                            within the funnel.{' '}
                                            <Link to="https://posthog.com/docs/product-analytics/correlation">
                                                Learn more about correlation analysis.
                                            </Link>
                                        </p>
                                        <LemonButton
                                            type="secondary"
                                            onClick={() => setIsPropertiesOpen(true)}
                                            className="mx-auto !mt-2"
                                        >
                                            Select properties
                                        </LemonButton>
                                    </>
                                )}
                            </div>
                        </div>
                    }
                    pagination={{
                        pageSize: 5,
                        hideOnSinglePage: true,
                        onBackward: () =>
                            reportCorrelationInteraction(FunnelCorrelationResultsType.Properties, 'pagination change', {
                                direction: 'backward',
                                page_size: 5,
                            }),
                        onForward: () =>
                            reportCorrelationInteraction(FunnelCorrelationResultsType.Properties, 'pagination change', {
                                direction: 'forward',
                                page_size: 5,
                            }),
                    }}
                />
            </div>
        </VisibilitySensor>
    ) : null
}
