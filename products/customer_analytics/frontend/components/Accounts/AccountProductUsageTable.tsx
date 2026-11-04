import './AccountProductUsageTable.scss'

import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonCheckbox, LemonSegmentedButton } from '@posthog/lemon-ui'

import { DotMatrix } from 'lib/components/DotMatrix/DotMatrix'

import type { BookActivityMatrixFirstUse, BookActivityMatrixResult } from '~/queries/schema/schema-general'

import { ProductUsageCountCell } from '../ProductUsageGrid/ProductUsageCountCell'
import { getProductUsageFirstSeries } from '../ProductUsageGrid/productUsagePresentation'
import { accountProductUsageLogic } from './accountProductUsageLogic'

export function AccountProductUsageTable({
    result,
    accountId,
    instanceId,
    includeFirstUse,
    firstUse = [],
    onIncludeFirstUseChange,
    loading,
    renderTopUsers,
    renderUserDetails,
}: {
    result: BookActivityMatrixResult
    accountId: string
    instanceId: string
    includeFirstUse: boolean
    firstUse?: BookActivityMatrixFirstUse[]
    onIncludeFirstUseChange: (value: boolean) => void
    loading?: boolean
    renderTopUsers?: (productKey: string) => ReactNode
    renderUserDetails?: (productKey: string, columnKey: string) => ReactNode
}): JSX.Element {
    const logic = accountProductUsageLogic({ instanceId, accountId, result })
    const { grouping, presentation } = useValues(logic)
    const { setGrouping } = useActions(logic)
    const rowByKey = new Map(presentation.rows.map((row) => [row.key, row]))
    return (
        <div className="AccountProductUsageTable flex flex-col gap-3 min-w-0" data-attr="account-product-usage-table">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonSegmentedButton
                    value={grouping}
                    onChange={setGrouping}
                    options={result.groupings.map(({ key, label }) => ({ value: key, label }))}
                    size="small"
                    data-attr="account-product-usage-grouping"
                />
                <LemonCheckbox
                    checked={includeFirstUse}
                    onChange={onIncludeFirstUseChange}
                    disabled={loading}
                    label="Show first use"
                    data-attr="account-product-usage-first-use"
                />
            </div>
            <DotMatrix
                {...presentation}
                emptyState="No product activity in this date range. Change the range or check the data source."
                loading={loading}
                rowClassName={(row) => `AccountProductUsageTable__${rowByKey.get(row.key)?.kind}`}
                rowHeader={{
                    ...presentation.rowHeader!,
                    render: (row) => (
                        <span className="flex items-center gap-2">
                            {rowByKey.get(row.key)?.productKey && (
                                <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true">
                                    <circle cx="4" cy="4" r="4" fill={rowByKey.get(row.key)?.color} />
                                </svg>
                            )}
                            <span>{row.label}</span>
                        </span>
                    ),
                }}
                renderCell={(cell) => {
                    const row = rowByKey.get(cell.rowKey)!
                    if (row.kind === 'group') {
                        return null
                    }
                    return (
                        <ProductUsageCountCell
                            value={cell.data[0]?.value ?? 0}
                            users={row.kind !== 'summary'}
                            firstUse={
                                includeFirstUse &&
                                !!row.productKey &&
                                getProductUsageFirstSeries(firstUse, accountId, cell.columnKey, 'week').includes(
                                    row.productKey
                                )
                            }
                            label={row.kind === 'summary' ? 'Products used' : `${row.label} users`}
                        />
                    )
                }}
                renderTooltip={(cell) => {
                    const row = rowByKey.get(cell.rowKey)!
                    return row.productKey && renderUserDetails
                        ? renderUserDetails(row.productKey, cell.columnKey)
                        : null
                }}
                trailingColumns={
                    renderTopUsers
                        ? [
                              {
                                  key: 'top-users',
                                  title: 'Top users, latest period',
                                  width: 160,
                                  render: (rowKey) => {
                                      const row = rowByKey.get(rowKey)!
                                      return row.productKey ? renderTopUsers(row.productKey) : null
                                  },
                              },
                          ]
                        : []
                }
            />
        </div>
    )
}
