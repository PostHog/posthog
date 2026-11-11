import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'

import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { percentage } from 'lib/utils/numbers'

import { PropertyDefinitionTypeNameEnumApi } from '~/generated/core/api.schemas'
import type { PropertyUsageEntryApi, PropertyValueCountApi } from '~/generated/core/api.schemas'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { propertyValueCountsLogic } from './propertyValueCountsLogic'

const formatCount = (value: number): string => value.toLocaleString()

function timesSentTooltip(type: PropertyUsageEntryApi['type']): string {
    const counted =
        type === PropertyDefinitionTypeNameEnumApi.Person
            ? 'Counts each event that carried this person property.'
            : type === PropertyDefinitionTypeNameEnumApi.Group
              ? 'Counts each time a group was updated with this property.'
              : 'Counts each event that sent this property.'
    return `${counted} A value drops out of the count when it hasn't been sent for 30 days.`
}

export function PropertyValueCountsSection({ entry }: { entry: PropertyUsageEntryApi }): JSX.Element {
    const { valueCounts, valueCountsLoading, valueCountsFailed } = useValues(propertyValueCountsLogic({ entry }))
    const totalCount = valueCounts?.total_count ?? 0

    const columns: LemonTableColumns<PropertyValueCountApi> = [
        {
            title: 'Value',
            key: 'value',
            render: function renderValue(_, row) {
                return <span className="break-all">{row.value}</span>
            },
        },
        {
            title: 'Times sent',
            key: 'count',
            align: 'right',
            render: function renderCount(_, row) {
                return formatCount(row.count)
            },
        },
        {
            title: 'Share',
            key: 'share',
            align: 'right',
            render: function renderShare(_, row) {
                return totalCount > 0 ? percentage(row.count / totalCount, 1) : null
            },
        },
    ]

    return (
        <SceneSection title="Values" description="How often this property was sent, and its most common values.">
            <div className="flex flex-wrap items-start gap-2">
                <AnalyticsMetricCard
                    className="flex-1 basis-60"
                    dataAttr="definition-usage-times-sent"
                    title={
                        <span className="inline-flex items-center gap-1">
                            Times sent
                            <Tooltip title={timesSentTooltip(entry.type)}>
                                <IconInfo className="text-tertiary" />
                            </Tooltip>
                        </span>
                    }
                    value={valueCounts?.total_count}
                    formatValue={formatCount}
                    showChange={false}
                    subtitle={
                        valueCounts
                            ? valueCounts.total_count === 0
                                ? 'No values recorded in the last 30 days'
                                : `${formatCount(valueCounts.distinct_value_count)} distinct ${valueCounts.distinct_value_count === 1 ? 'value' : 'values'}`
                            : undefined
                    }
                    loading={valueCountsLoading}
                    error={
                        valueCountsFailed
                            ? "Couldn't load how often this property was sent. Refresh the page to try again."
                            : undefined
                    }
                />
                {!valueCountsFailed && (valueCountsLoading || totalCount > 0) && (
                    <div className="flex min-w-0 flex-[3] basis-96 flex-col gap-2">
                        <LemonTable
                            columns={columns}
                            dataSource={valueCounts?.values ?? []}
                            loading={valueCountsLoading}
                            loadingSkeletonRows={5}
                            rowKey="value"
                            data-attr="definition-usage-top-values-table"
                            nouns={['value', 'values']}
                        />
                        {valueCounts?.is_approximate && (
                            <p className="text-secondary text-xs m-0">
                                This property has many distinct values, so the most common values and their counts are
                                estimates.
                            </p>
                        )}
                    </div>
                )}
            </div>
        </SceneSection>
    )
}
