import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo, useState } from 'react'

import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { DefinitionPopoverRendererProps, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { hogqlQuery } from '~/queries/query'
import { hogql } from '~/queries/utils'

import { TablePreview } from './TablePreview'
import { DataWarehouseTableForInsight } from './types'

const TIMESTAMP_FIELD_FALLBACKS = ['created', 'created_at', 'createdAt', 'updated', 'updated_at', 'updatedAt']

function resolveTimestampField(table: DataWarehouseTableForInsight, configuredTimestampField?: string): string | null {
    const tableFieldNames = new Set(Object.values(table.fields).map((field) => field.name))

    if (configuredTimestampField) {
        return tableFieldNames.has(configuredTimestampField) ? configuredTimestampField : null
    }

    const fallbackFieldFromName = Object.values(table.fields).find((field) =>
        TIMESTAMP_FIELD_FALLBACKS.includes(field.name)
    )
    if (fallbackFieldFromName) {
        return fallbackFieldFromName.name
    }

    const fallbackFieldFromType = Object.values(table.fields).find(
        (field) => field.type === 'datetime' || field.type === 'date'
    )
    return fallbackFieldFromType?.name ?? null
}

function transformPreviewResponse(response: { columns?: string[]; results?: any[][] }): Record<string, any>[] {
    return (response.results || []).map((row: any[]) =>
        Object.fromEntries((response.columns || []).map((column: string, index: number) => [column, row[index]]))
    )
}

export function DataWarehouseFunnelStepDefinitionPopover({
    item,
    group,
    defaultView,
}: DefinitionPopoverRendererProps): JSX.Element | null {
    if (group.type !== TaxonomicFilterGroupType.DataWarehouse || !('fields' in item)) {
        return null
    }

    const { insightProps } = useValues(insightLogic)
    const { querySource, insightData } = useValues(funnelDataLogic(insightProps))
    const { localDefinition } = useValues(definitionPopoverLogic)

    const [previewData, setPreviewData] = useState<Record<string, any>[]>([])
    const [previewLoading, setPreviewLoading] = useState(false)

    const table = item as DataWarehouseTableForInsight
    const configuredTimestampField =
        typeof (localDefinition as { timestamp_field?: unknown })?.timestamp_field === 'string'
            ? String((localDefinition as { timestamp_field?: string }).timestamp_field)
            : undefined
    const timestampField = useMemo(
        () => resolveTimestampField(table, configuredTimestampField),
        [configuredTimestampField, table]
    )
    const tableName = table.name
    const dateFrom = insightData?.resolved_date_range?.date_from ?? querySource?.dateRange?.date_from
    const dateTo = insightData?.resolved_date_range?.date_to ?? querySource?.dateRange?.date_to

    useEffect(() => {
        let isCanceled = false

        const loadPreview = async (): Promise<void> => {
            setPreviewLoading(true)
            try {
                const parsedDateFrom = dateFrom && dateFrom !== 'all' ? dayjs(dateFrom) : null
                const parsedDateTo = dateTo && dateTo !== 'all' ? dayjs(dateTo) : null
                const filters: string[] = []
                if (timestampField && parsedDateFrom?.isValid()) {
                    filters.push(String(hogql`${hogql.identifier(timestampField)} >= ${parsedDateFrom}`))
                }
                if (timestampField && parsedDateTo?.isValid()) {
                    filters.push(String(hogql`${hogql.identifier(timestampField)} <= ${parsedDateTo}`))
                }

                const whereClause = filters.length > 0 ? ` WHERE ${filters.join(' AND ')}` : ''
                const previewQuery = hogql`SELECT * FROM ${hogql.identifier(tableName)}${hogql.raw(
                    whereClause
                )} LIMIT 10`
                const response = await hogqlQuery(previewQuery)

                if (!isCanceled) {
                    setPreviewData(transformPreviewResponse(response))
                }
            } catch (error) {
                posthog.captureException(error)
                if (!isCanceled) {
                    setPreviewData([])
                }
            } finally {
                if (!isCanceled) {
                    setPreviewLoading(false)
                }
            }
        }

        void loadPreview()

        return () => {
            isCanceled = true
        }
    }, [dateFrom, dateTo, tableName, timestampField])

    return (
        <div className="space-y-3 w-100">
            <TablePreview
                table={table}
                emptyMessage="Select a data warehouse table to view preview"
                previewData={previewData}
                loading={previewLoading}
                selectedKey={timestampField}
                heightClassName="h-48"
            />
            {defaultView}
        </div>
    )
}
