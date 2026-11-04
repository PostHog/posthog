import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { LemonTable, Link } from '@posthog/lemon-ui'

import { CountCell } from 'lib/components/DotMatrix/CountCell'
import { dayjs } from 'lib/dayjs'

import type { BookActivityMatrixResult } from '~/queries/schema/schema-general'

import type { AccountViewApi } from '../../generated/api.schemas'
import { getAccountProductActivityUrl } from '../Accounts/accountProductActivityUrl'
import {
    indexProductUsageCounts,
    indexProductUsagePeople,
    indexProductUsageFirsts,
    productUsageCellKey,
    productUsageRows,
    type ProductUsageTableRow,
} from './productUsageData'
import { productUsageGridLogic } from './productUsageGridLogic'
import { ProductUsageNamesCell } from './ProductUsageNamesCell'
import { getProductUsageCountScale } from './productUsagePresentation'

export function ProductUsageUsersTable({
    matrix,
    views,
}: {
    matrix: BookActivityMatrixResult
    views: AccountViewApi[]
}): JSX.Element {
    const { controls, result, focusedCell, userPage, details, detailsLoading, expanded, extraPeople, peopleLoading } =
        useValues(productUsageGridLogic)
    const { togglePeople, setUserPage } = useActions(productUsageGridLogic)
    const page = Math.min(userPage, Math.max(1, Math.ceil(matrix.rows.length / 5)))
    const rows = productUsageRows(
        { ...matrix, rows: matrix.rows.slice((page - 1) * 5, page * 5) },
        controls.selected,
        'users'
    )
    const counts = useMemo(() => indexProductUsageCounts(matrix, controls.selected), [matrix, controls.selected])
    const totals = useMemo(
        () => new Map(matrix.data.map((cell) => [productUsageCellKey(cell.row, cell.column, cell.series), cell.users])),
        [matrix]
    )
    const peopleByCell = useMemo(() => {
        const people = (details.people?.people ?? []).filter(
            (person) =>
                !expanded[JSON.stringify([person.row, person.series])] ||
                !extraPeople[JSON.stringify([person.row, person.series])]
        )
        for (const [key, extra] of Object.entries(extraPeople)) {
            if (expanded[key]) {
                people.push(...extra)
            }
        }
        return indexProductUsagePeople(people)
    }, [details.people, expanded, extraPeople])
    const firstsByProduct = useMemo(
        () => indexProductUsageFirsts(controls.firstUse ? (details.firsts?.people ?? []) : []),
        [controls.firstUse, details.firsts]
    )
    const container = useRef<HTMLDivElement>(null)
    useEffect(() => {
        if (!focusedCell) {
            return
        }
        const cell = Array.from(container.current?.querySelectorAll<HTMLElement>('[data-activity-focus]') ?? []).find(
            (node) =>
                node.dataset.accountId === focusedCell.accountId && node.dataset.columnKey === focusedCell.columnKey
        )
        cell?.focus({ preventScroll: true })
        cell?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    }, [focusedCell, page])
    return (
        <div ref={container}>
            <LemonTable<ProductUsageTableRow>
                dataSource={rows}
                rowKey="key"
                pagination={{
                    controlled: true,
                    pageSize: 5,
                    currentPage: page,
                    entryCount: matrix.rows.length,
                    onForward: page * 5 < matrix.rows.length ? () => setUserPage(page + 1) : undefined,
                    onBackward: page > 1 ? () => setUserPage(page - 1) : undefined,
                }}
                nouns={['account', 'accounts']}
                firstColumnSticky
                columns={[
                    {
                        key: 'name',
                        title: 'Account / product',
                        width: 220,
                        render: (_, row) =>
                            row.productKey ? (
                                <span className="pl-4 text-secondary">{row.label}</span>
                            ) : (
                                <Link to={getAccountProductActivityUrl(row.accountId, views)}>{row.label}</Link>
                            ),
                    },
                    ...matrix.columns.map((column) => ({
                        key: column.key,
                        title: `${dayjs(column.key).format('MMM D')}${column.partial ? ' (to date)' : ''}`,
                        width: 150,
                        render: (_: unknown, row: ProductUsageTableRow) => {
                            if (!row.productKey) {
                                return (
                                    <div
                                        tabIndex={-1}
                                        data-activity-focus
                                        data-account-id={row.accountId}
                                        data-column-key={column.key}
                                    >
                                        <CountCell
                                            value={counts.get(productUsageCellKey(row.accountId, column.key)) ?? 0}
                                            scale={getProductUsageCountScale(controls.selected.length > 0)}
                                        />
                                    </div>
                                )
                            }
                            const key = JSON.stringify([row.accountId, row.productKey])
                            const cellKey = productUsageCellKey(row.accountId, column.key, row.productKey)
                            return (
                                <ProductUsageNamesCell
                                    people={peopleByCell.get(cellKey) ?? []}
                                    total={totals.get(cellKey) ?? 0}
                                    firstUse={firstsByProduct.get(key) ?? []}
                                    columnKey={column.key}
                                    interval={result?.interval ?? controls.interval}
                                    expanded={!!expanded[key]}
                                    loading={detailsLoading || peopleLoading[key]}
                                    onToggle={() => togglePeople(row.accountId, row.productKey!)}
                                />
                            )
                        },
                    })),
                ]}
            />
        </div>
    )
}
