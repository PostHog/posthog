import './DotMatrixDemo.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Sparkline } from 'lib/components/Sparkline'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { CountCell } from './CountCell'
import { DotMatrix } from './DotMatrix'
import { DotMatrixDemoAccountTooltip } from './DotMatrixDemoAccountTooltip'
import { dotMatrixDemoLogic, type DotMatrixDemoLogicProps } from './dotMatrixDemoLogic'
import { DotMatrixDemoTooltip } from './DotMatrixDemoTooltip'
import { DotMatrixDemoUserTooltip } from './DotMatrixDemoUserTooltip'
import { DotMatrixUserCell } from './DotMatrixUserCell'
import {
    DOT_MATRIX_MOCK_ACCOUNTS,
    DOT_MATRIX_MOCK_GROUPS,
    DOT_MATRIX_MOCK_PRODUCTS,
    DOT_MATRIX_PRODUCT_COUNT_SCALE,
    DOT_MATRIX_USER_COUNT_SCALE,
    type DotMatrixMockDatum,
} from './mocks'
import type { DotMatrixAxisItem, DotMatrixCell } from './types'

export interface DotMatrixDemoProps extends DotMatrixDemoLogicProps {
    width?: 'reference' | 'narrow' | 'wide'
    loading?: boolean
    empty?: boolean
}

export function DotMatrixDemo({ width = 'reference', loading, empty, ...props }: DotMatrixDemoProps): JSX.Element {
    const generatedId = useId()
    const logic = dotMatrixDemoLogic({ ...props, instanceId: `${props.instanceId}:${generatedId}` })
    const { datasetName, mode, selectedSeries, colorMode, dataset, presentation, display } = useValues(logic)
    const { setDatasetName, setMode, setSelectedSeries, setColorMode, openAccount } = useActions(logic)
    const { isProducts, isDetail, displayed, series, rowPeople, trends, trendMax, accountMeta, activePeopleCount } =
        display
    const { countScale, legend, trendColor } = presentation
    const itemLabel = legend.itemLabel

    const renderRowHeader = (row: DotMatrixAxisItem): JSX.Element => {
        const account = DOT_MATRIX_MOCK_ACCOUNTS.find((item) => item.id === row.key)
        if (account) {
            return (
                <div className="DotMatrixDemo__account-label">
                    <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
                        <rect width="24" height="24" rx="5" fill={account.logo} />
                        <text
                            x="12"
                            y="12"
                            dominantBaseline="central"
                            textAnchor="middle"
                            fill="#ffffff"
                            fontSize="12"
                            fontWeight="700"
                        >
                            {account.name[0]}
                        </text>
                    </svg>
                    <div className="DotMatrixDemo__label-copy">
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            className="DotMatrixDemo__account-name"
                            onClick={() => openAccount(account.id)}
                            data-attr="dot-matrix-open-account"
                        >
                            {account.name}
                        </LemonButton>
                        <span>{accountMeta.get(account.id)}</span>
                    </div>
                </div>
            )
        }
        if (row.group === 'family') {
            return <span className="DotMatrixDemo__family-label">{row.label}</span>
        }
        const productKey = row.key.split('/')[1]
        const index = DOT_MATRIX_MOCK_PRODUCTS.findIndex(([key]) => key === productKey)
        if (index >= 0) {
            const persons = rowPeople.get(row.key) ?? []
            return (
                <div className="DotMatrixDemo__product-label">
                    <span>
                        <svg width="8" height="8" aria-hidden="true">
                            <circle
                                cx="4"
                                cy="4"
                                r="4"
                                fill={
                                    colorMode === 'product'
                                        ? DOT_MATRIX_MOCK_PRODUCTS[index][2]
                                        : DOT_MATRIX_MOCK_GROUPS[Math.floor(index / 6)].color
                                }
                            />
                        </svg>
                        <span>{row.label}</span>
                    </span>
                    <small>{`${persons.length} users`}</small>
                </div>
            )
        }
        return <span>{row.label ?? row.key}</span>
    }

    const renderDetailCell = (cell: DotMatrixCell<DotMatrixMockDatum>): JSX.Element | null => {
        const row = displayed.rows?.find((item) => item.key === cell.rowKey)
        if (row?.group === 'family') {
            return null
        }
        if (mode === 'users' && row?.group !== 'account') {
            const product = DOT_MATRIX_MOCK_PRODUCTS.find(([key]) => key === cell.rowKey.split('/')[1])?.[1] ?? ''
            return (
                <DotMatrixUserCell
                    persons={cell.data[0]?.persons ?? []}
                    renderTooltip={(person) => (
                        <DotMatrixDemoUserTooltip person={person} product={product} week={cell.columnKey} />
                    )}
                />
            )
        }
        return (
            <CountCell
                size={mode === 'account' ? 'small' : 'xsmall'}
                value={cell.data[0]?.value ?? 0}
                scale={
                    row?.group === 'summary' || (row?.group === 'account' && !selectedSeries.length)
                        ? DOT_MATRIX_PRODUCT_COUNT_SCALE
                        : DOT_MATRIX_USER_COUNT_SCALE
                }
            />
        )
    }
    const rows = empty ? [] : displayed.rows
    const columns = displayed.columns ?? []
    return (
        <div className={clsx('DotMatrixDemo', `DotMatrixDemo--${width}`, `DotMatrixDemo--${mode}`)}>
            <div className="DotMatrixDemo__toolbar">
                <div className="DotMatrixDemo__dataset">
                    <LemonSelect
                        value={datasetName}
                        onChange={setDatasetName}
                        options={[
                            { value: 'product_activity', label: 'Product activity' },
                            { value: 'people', label: 'People in one account' },
                            { value: 'ci', label: 'CI health' },
                        ]}
                        size="small"
                        data-attr="dot-matrix-dataset"
                    />
                    <span className="text-muted text-xs">Mock data</span>
                </div>
                <div className="DotMatrixDemo__controls">
                    {isProducts && (
                        <LemonSelect
                            value={colorMode}
                            onChange={setColorMode}
                            options={[
                                { value: 'family', label: 'Color per family' },
                                { value: 'product', label: 'Color per product' },
                            ]}
                            size="small"
                        />
                    )}
                    <span className="DotMatrixDemo__range">Last 8 weeks</span>
                    <LemonSegmentedButton
                        value={mode}
                        onChange={setMode}
                        size="small"
                        options={[
                            { value: 'count', label: 'Count', 'data-attr': 'dot-matrix-count-mode' },
                            {
                                value: 'products',
                                label: isProducts ? 'Products' : 'Dots',
                                'data-attr': 'dot-matrix-dots-mode',
                            },
                            ...(isProducts
                                ? [
                                      { value: 'users' as const, label: 'Users', 'data-attr': 'dot-matrix-users-mode' },
                                      {
                                          value: 'account' as const,
                                          label: 'Account',
                                          'data-attr': 'dot-matrix-account-mode',
                                      },
                                  ]
                                : []),
                        ]}
                    />
                </div>
            </div>
            {mode === 'account' && isProducts && (
                <div className="DotMatrixDemo__account-heading">
                    <h3>Product activity</h3>
                    <span className="text-muted">
                        A user counts when they take a product action, or spend 30s to 30 min on its pages.
                    </span>
                </div>
            )}
            <DotMatrix
                {...displayed}
                data={empty ? [] : displayed.data}
                rows={rows}
                series={mode === 'account' && isProducts ? [] : series}
                groups={dataset.groups}
                mode={mode === 'products' ? 'dots' : 'count'}
                countScale={countScale}
                selectedSeries={selectedSeries}
                onSelectedSeriesChange={setSelectedSeries}
                aggregateSelection={dataset.aggregateSelection}
                rowHeader={{
                    ...displayed.rowHeader,
                    width: mode === 'account' && isProducts ? 190 : 220,
                    title: displayed.rowHeader?.title ?? 'Row',
                    render: isProducts ? renderRowHeader : undefined,
                }}
                renderCell={isDetail ? renderDetailCell : undefined}
                renderTooltip={
                    datasetName !== 'ci' && !isDetail
                        ? (cell) => (
                              <DotMatrixDemoTooltip
                                  cell={cell}
                                  selectedSeries={selectedSeries}
                                  datasetName={datasetName}
                              />
                          )
                        : mode === 'account' && isProducts
                          ? (cell) =>
                                cell.rowKey === 'summary' || cell.rowKey.startsWith('group:') ? null : (
                                    <DotMatrixDemoAccountTooltip cell={cell} />
                                )
                          : mode === 'users' && isProducts
                            ? () => null
                            : undefined
                }
                rowClassName={
                    isDetail
                        ? (row) =>
                              row.group === 'account'
                                  ? 'DotMatrixDemo__account-row'
                                  : row.group === 'family'
                                    ? 'DotMatrixDemo__family-row'
                                    : row.group === 'summary'
                                      ? 'DotMatrixDemo__summary-row'
                                      : 'DotMatrixDemo__product-row'
                        : undefined
                }
                cellWidth={mode === 'users' ? 110 : mode === 'account' && isProducts ? 62 : undefined}
                legend={
                    mode === 'account' && isProducts
                        ? false
                        : {
                              ...legend,
                              selectionLabel: (count) =>
                                  `Showing ${count} ${count === 1 ? itemLabel : `${itemLabel}s`}`,
                              footer:
                                  mode === 'users' && isProducts ? (
                                      <span>Most active first. Hover a name to see what qualified them.</span>
                                  ) : undefined,
                          }
                }
                trailingColumns={
                    mode === 'count'
                        ? [
                              {
                                  key: 'trend',
                                  title: 'Trend',
                                  width: 132,
                                  render: (rowKey) => {
                                      return (
                                          <Sparkline
                                              data={trends.get(rowKey) ?? []}
                                              labels={columns.map((column) => column.label ?? column.key)}
                                              type="line"
                                              color={trendColor}
                                              valueDomain={{ min: 0, max: trendMax }}
                                              className="DotMatrixDemo__sparkline"
                                          />
                                      )
                                  },
                              },
                          ]
                        : mode === 'account' && isProducts
                          ? [
                                {
                                    key: 'top-users',
                                    title: 'Top users',
                                    width: 160,
                                    render: (rowKey) => {
                                        if (rowKey.startsWith('group:')) {
                                            return null
                                        }
                                        if (rowKey === 'summary') {
                                            return (
                                                <span className="DotMatrixDemo__top-users">{`${activePeopleCount} active users`}</span>
                                            )
                                        }
                                        const persons = rowPeople.get(rowKey) ?? []
                                        return (
                                            <span className="DotMatrixDemo__top-users">
                                                {persons
                                                    .slice(0, 3)
                                                    .map((person) => person.name)
                                                    .join(', ')}
                                                {persons.length > 3 ? ` +${persons.length - 3}` : ''}
                                            </span>
                                        )
                                    },
                                },
                            ]
                          : []
                }
                loading={loading}
            />
        </div>
    )
}
