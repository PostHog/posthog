import { useActions, useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { DotMatrix } from 'lib/components/DotMatrix/DotMatrix'

import { accountViewsLogic } from '../../scenes/CustomerAnalyticsAccountScene/accountViewsLogic'
import { getAccountProductActivityUrl } from '../Accounts/accountProductActivityUrl'
import { getBookActivityMatrixProps } from '../Accounts/bookActivityMatrix'
import { getHogQLActivityMatrix, getHogQLLimitNotice } from '../Accounts/hogqlActivityMatrix'
import { ProductUsageGlyph } from './ProductUsageGlyph'
import { productUsageGridLogic } from './productUsageGridLogic'
import { ProductUsageLegend } from './ProductUsageLegend'
import { getProductUsageCountScale } from './productUsagePresentation'
import { ProductUsageUsersTable } from './ProductUsageUsersTable'

export function ProductUsageGrid(): JSX.Element | null {
    const { currentTeamId, result, controls, mappingDraft, editorOpen, details, loading } =
        useValues(productUsageGridLogic)
    const { views } = useValues(accountViewsLogic({ projectId: currentTeamId! }))
    const { setControls, zoomToCell } = useActions(productUsageGridLogic)
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
    const props = getBookActivityMatrixProps(matrix, controls.selected)
    return (
        <div className="border rounded p-3 flex flex-col gap-3" data-attr="product-activity-grid">
            <ProductUsageLegend
                series={matrix.series}
                groupings={matrix.groupings}
                grouping={controls.grouping}
                onGroupingChange={(grouping) => setControls({ grouping })}
                selectedSeries={controls.selected}
                onSelectedSeriesChange={(selected) => setControls({ selected })}
                mode={controls.zoom === 'products' ? 'dots' : 'count'}
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
                        render: (row) => <Link to={getAccountProductActivityUrl(row.key, views)}>{row.label}</Link>,
                    }}
                    renderCell={
                        controls.zoom === 'products'
                            ? (cell) => (
                                  <ProductUsageGlyph
                                      result={matrix}
                                      rowKey={cell.rowKey}
                                      columnKey={cell.columnKey}
                                      values={cell.values}
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
