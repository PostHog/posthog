import { useActions, useValues } from 'kea'
import { useLayoutEffect, useMemo, useRef, useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { DotMatrix } from 'lib/components/DotMatrix/DotMatrix'
import { Sparkline } from 'lib/components/Sparkline'

import { accountViewsLogic } from '../../scenes/CustomerAnalyticsAccountScene/accountViewsLogic'
import { getBookActivityMatrixProps } from '../Accounts/bookActivityMatrix'
import { getHogQLActivityMatrix, getHogQLLimitNotice } from '../ProductActivity/hogqlActivityMatrix'
import {
    getActivityMatrixEmptyMessage,
    getProductUsageCountLabel,
    getProductUsageCountScale,
} from '../ProductActivity/productUsagePresentation'
import { ProductUsageAccountCell } from './ProductUsageAccountCell'
import { ProductUsageCellTooltip } from './ProductUsageCellTooltip'
import { indexProductUsageBreadth, indexProductUsageCounts, productUsageCellKey } from './productUsageData'
import { ProductUsageGlyph } from './ProductUsageGlyph'
import { productUsageGridLogic } from './productUsageGridLogic'
import { ProductUsageLegend } from './ProductUsageLegend'
import { ProductUsageUsersTable } from './ProductUsageUsersTable'

export function ProductUsageGrid(): JSX.Element | null {
    const { currentTeamId, result, controls, mappingDraft, editorOpen, details, loading, focusedCell } =
        useValues(productUsageGridLogic)
    const { views } = useValues(accountViewsLogic({ projectId: currentTeamId! }))
    const { setControls, zoomToCell } = useActions(productUsageGridLogic)
    const [hoveredSeries, setHoveredSeries] = useState<string | null>(null)
    const matrixProps = useMemo(
        () => (result?.matrix ? getBookActivityMatrixProps(result.matrix, controls.selected) : null),
        [result?.matrix, controls.selected]
    )
    const counts = useMemo(
        () => (result?.matrix ? indexProductUsageCounts(result.matrix, controls.selected) : new Map<string, number>()),
        [result?.matrix, controls.selected]
    )
    const breadth = useMemo(
        () => (result?.matrix ? indexProductUsageBreadth(result.matrix, controls.selected) : new Map<string, number>()),
        [result?.matrix, controls.selected]
    )
    const container = useRef<HTMLDivElement>(null)
    useLayoutEffect(() => {
        if (controls.zoom !== 'products' || !focusedCell) {
            return
        }
        const cell = Array.from(
            container.current?.querySelectorAll<HTMLElement>('[data-attr="dot-matrix-cell"]') ?? []
        ).find(
            (node) => node.dataset.rowKey === focusedCell.accountId && node.dataset.columnKey === focusedCell.columnKey
        )
        cell?.focus({ preventScroll: true })
        cell?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    }, [controls.zoom, focusedCell])
    if (!result) {
        return null
    }
    if (result.hogql && result.source.kind === 'hogql') {
        const mapping = editorOpen ? mappingDraft : result.source.mapping
        const mapped = getHogQLActivityMatrix(result.hogql, mapping)
        const labels = new Map<string, string>()
        for (const account of result.accounts.results) {
            labels.set(account.id, account.name)
            if (account.externalId) {
                labels.set(account.externalId, account.name)
            }
        }
        const props =
            mapped.props && !mapping.rowLabel
                ? {
                      ...mapped.props,
                      rows: mapped.props.rows?.map((row) => ({ ...row, label: labels.get(row.key) ?? row.label })),
                  }
                : mapped.props
        const notice = getHogQLLimitNotice(result.hogql, result.source.query)
        return (
            <div className="flex flex-col gap-2">
                {[
                    ...mapped.notices,
                    ...(notice ? [notice] : []),
                    ...(result.hogql.hasMore
                        ? ['The query result is incomplete. Narrow the query or raise its limit.']
                        : []),
                ].map((message) => (
                    <LemonBanner key={message} type="info">
                        {message}
                    </LemonBanner>
                ))}
                {mapped.error ? (
                    <LemonBanner type="error">{mapped.error}</LemonBanner>
                ) : (
                    props && (
                        <DotMatrix
                            {...props}
                            countOf={props.countOf ?? 'value'}
                            mode={controls.zoom === 'count' ? 'count' : 'dots'}
                            selectedSeries={controls.selected}
                            onSelectedSeriesChange={(selected) => setControls({ selected })}
                            pageSize={20}
                            loading={loading}
                        />
                    )
                )}
            </div>
        )
    }
    if (!result.matrix) {
        return (
            <LemonBanner type="info">
                No accounts match these filters. Change the account filters and run the query again.
            </LemonBanner>
        )
    }
    const matrix = result.matrix
    const emptyMessage = getActivityMatrixEmptyMessage(matrix.emptyReason)
    if (emptyMessage) {
        return <LemonBanner type="info">{emptyMessage}</LemonBanner>
    }
    const props = matrixProps!
    return (
        <div ref={container} className="border rounded p-3 flex flex-col gap-3" data-attr="product-activity-grid">
            <ProductUsageLegend
                series={matrix.series}
                groupings={matrix.groupings}
                grouping={controls.grouping}
                onGroupingChange={(grouping) => setControls({ grouping })}
                selectedSeries={controls.selected}
                onSelectedSeriesChange={(selected) => setControls({ selected })}
                mode={controls.zoom === 'products' ? 'dots' : controls.zoom}
                hoveredSeries={hoveredSeries}
                onHoveredSeriesChange={setHoveredSeries}
                includeFirstUse={controls.firstUse}
            />
            {matrix.truncated && (
                <LemonBanner type="warning">
                    The grid is incomplete. Narrow the account filters or date range to see all activity.
                </LemonBanner>
            )}
            {controls.zoom === 'users' ? (
                <ProductUsageUsersTable matrix={matrix} views={views} />
            ) : (
                <DotMatrix
                    {...props}
                    mode={controls.zoom === 'count' ? 'count' : 'dots'}
                    legend={false}
                    countScale={getProductUsageCountScale(controls.selected.length > 0)}
                    selectedSeries={controls.selected}
                    pageSize={20}
                    rowHeader={{
                        title: 'Account',
                        width: 220,
                        render: (row) => (
                            <ProductUsageAccountCell
                                accountId={row.key}
                                name={row.label ?? row.key}
                                products={breadth.get(row.key) ?? 0}
                                truncated={matrix.truncated}
                                views={views}
                            />
                        ),
                    }}
                    trailingColumns={
                        controls.zoom === 'count'
                            ? [
                                  {
                                      key: 'trend',
                                      title: 'Trend',
                                      width: 116,
                                      render: (rowKey) => (
                                          <div
                                              aria-label={`${matrix.rows.find((row) => row.key === rowKey)?.label ?? rowKey}: ${getProductUsageCountLabel(matrix.series, controls.selected)} per period`}
                                          >
                                              <Sparkline
                                                  type="line"
                                                  className="!w-24 h-8"
                                                  data={matrix.columns.map(
                                                      (column) =>
                                                          counts.get(productUsageCellKey(rowKey, column.key)) ?? 0
                                                  )}
                                                  labels={matrix.columns.map((column) => column.key)}
                                                  name={getProductUsageCountLabel(matrix.series, controls.selected)}
                                              />
                                          </div>
                                      ),
                                  },
                              ]
                            : []
                    }
                    renderTooltip={(cell) => (
                        <ProductUsageCellTooltip
                            matrix={matrix}
                            rowKey={cell.rowKey}
                            columnKey={cell.columnKey}
                            values={cell.values}
                            selected={controls.selected}
                            interval={result.interval ?? controls.interval}
                            firstUse={controls.firstUse ? details.firsts?.accounts : []}
                        />
                    )}
                    renderCell={
                        controls.zoom === 'products'
                            ? (cell) => (
                                  <ProductUsageGlyph
                                      result={matrix}
                                      rowKey={cell.rowKey}
                                      columnKey={cell.columnKey}
                                      values={cell.values}
                                      hoveredSeries={hoveredSeries}
                                      grouping={controls.grouping}
                                      firstUse={controls.firstUse ? details.firsts?.accounts : []}
                                      interval={result.interval ?? controls.interval}
                                  />
                              )
                            : undefined
                    }
                    onCellClick={(cell) => zoomToCell(cell.rowKey, cell.columnKey)}
                    loading={loading}
                />
            )}
        </div>
    )
}
