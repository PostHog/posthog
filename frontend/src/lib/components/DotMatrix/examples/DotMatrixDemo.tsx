import './DotMatrixDemo.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Sparkline } from 'lib/components/Sparkline'

import { DotMatrix } from '../DotMatrix'
import { DotMatrixDemoAccountTooltip } from './DotMatrixDemoAccountTooltip'
import { DotMatrixDemoDetailCell } from './DotMatrixDemoDetailCell'
import { dotMatrixDemoLogic, type DotMatrixDemoLogicProps } from './dotMatrixDemoLogic'
import { DotMatrixDemoRowHeader } from './DotMatrixDemoRowHeader'
import { DotMatrixDemoToolbar } from './DotMatrixDemoToolbar'
import { DotMatrixDemoTooltip } from './DotMatrixDemoTooltip'
import { DotMatrixDemoTopUsers } from './DotMatrixDemoTopUsers'

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
    const isAccount = mode === 'account' && isProducts
    const isUsers = mode === 'users' && isProducts

    const rows = empty ? [] : displayed.rows
    const columns = displayed.columns ?? []
    return (
        <div className={clsx('DotMatrixDemo', `DotMatrixDemo--${width}`, `DotMatrixDemo--${mode}`)}>
            <DotMatrixDemoToolbar
                datasetName={datasetName}
                mode={mode}
                colorMode={colorMode}
                setDatasetName={setDatasetName}
                setMode={setMode}
                setColorMode={setColorMode}
            />
            {isAccount && (
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
                series={isAccount ? [] : series}
                groups={dataset.groups}
                mode={mode === 'products' ? 'dots' : 'count'}
                countScale={countScale}
                selectedSeries={selectedSeries}
                onSelectedSeriesChange={setSelectedSeries}
                aggregateSelection={dataset.aggregateSelection}
                rowHeader={{
                    ...displayed.rowHeader,
                    width: isAccount ? 190 : 220,
                    title: displayed.rowHeader?.title ?? 'Row',
                    render: isProducts
                        ? (row) => (
                              <DotMatrixDemoRowHeader
                                  row={row}
                                  colorMode={colorMode}
                                  rowPeople={rowPeople.get(row.key) ?? []}
                                  accountMeta={accountMeta.get(row.key)}
                                  openAccount={openAccount}
                              />
                          )
                        : undefined,
                }}
                renderCell={
                    isDetail
                        ? (cell) => (
                              <DotMatrixDemoDetailCell
                                  cell={cell}
                                  row={displayed.rows?.find((row) => row.key === cell.rowKey)}
                                  mode={mode}
                                  selectedSeries={selectedSeries}
                              />
                          )
                        : undefined
                }
                renderTooltip={
                    datasetName !== 'ci' && !isDetail
                        ? (cell) => (
                              <DotMatrixDemoTooltip
                                  cell={cell}
                                  selectedSeries={selectedSeries}
                                  datasetName={datasetName}
                              />
                          )
                        : isAccount
                          ? (cell) =>
                                cell.rowKey === 'summary' || cell.rowKey.startsWith('group:') ? null : (
                                    <DotMatrixDemoAccountTooltip cell={cell} />
                                )
                          : isUsers
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
                cellWidth={mode === 'users' ? 110 : isAccount ? 62 : undefined}
                legend={
                    isAccount
                        ? false
                        : {
                              ...legend,
                              selectionLabel: (count) =>
                                  `Showing ${count} ${count === 1 ? itemLabel : `${itemLabel}s`}`,
                              footer: isUsers ? (
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
                        : isAccount
                          ? [
                                {
                                    key: 'top-users',
                                    title: 'Top users',
                                    width: 160,
                                    render: (rowKey) => {
                                        return (
                                            <DotMatrixDemoTopUsers
                                                rowKey={rowKey}
                                                activePeopleCount={activePeopleCount}
                                                people={rowPeople.get(rowKey) ?? []}
                                            />
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
