import { getDotMatrixCellCount, normalizeDotMatrixData } from '../dotMatrixData'
import type { DotMatrixCell, DotMatrixSeries } from '../types'
import type { DotMatrixDemoMode } from './dotMatrixDemoLogic'
import { getDotMatrixAccountMeta, getDotMatrixDetailDataset } from './dotMatrixDetailData'
import { DOT_MATRIX_MOCK_ACCOUNTS, DOT_MATRIX_MOCK_PRODUCTS } from './dotMatrixMockFixtures'
import {
    type DotMatrixMockDataset,
    type DotMatrixMockDatasetName,
    type DotMatrixMockDatum,
    type DotMatrixMockPerson,
} from './dotMatrixMockTypes'
import { getDotMatrixMockPeople } from './mocks'

export function getDotMatrixSelectionSummary(
    cell: DotMatrixCell<DotMatrixMockDatum>,
    selectedSeries: string[]
): { distinct: number; overlap: number } {
    const selected = new Set(selectedSeries)
    const memberships = new Map<string, Set<string>>()
    for (const datum of cell.data) {
        if (datum.value <= 0 || (selected.size > 0 && !selected.has(datum.seriesKey))) {
            continue
        }
        for (const person of datum.persons) {
            const series = memberships.get(person.id) ?? new Set<string>()
            series.add(datum.seriesKey)
            memberships.set(person.id, series)
        }
    }
    return {
        distinct: memberships.size,
        overlap: [...memberships.values()].filter((series) => series.size > 1).length,
    }
}

export interface DotMatrixDemoDisplay {
    isProducts: boolean
    isDetail: boolean
    displayed: DotMatrixMockDataset
    series: DotMatrixSeries[] | undefined
    trends: Map<string, number[]>
    trendMax: number
    rowPeople: Map<string, DotMatrixMockPerson[]>
    accountMeta: Map<string, string>
    activePeopleCount: number
}

export function getDotMatrixDemoDisplay(
    dataset: DotMatrixMockDataset,
    datasetName: DotMatrixMockDatasetName,
    mode: DotMatrixDemoMode,
    selectedSeries: string[],
    colorMode: 'family' | 'product',
    activeAccount: string
): DotMatrixDemoDisplay {
    const isProducts = datasetName === 'product_activity'
    const isDetail = isProducts && (mode === 'users' || mode === 'account')
    const displayed = isDetail
        ? getDotMatrixDetailDataset(dataset.data, selectedSeries, mode === 'account', activeAccount)
        : dataset
    const matrix = normalizeDotMatrixData(dataset)
    const factsByRow = new Map<string, DotMatrixMockDatum[]>()
    for (const datum of displayed.data) {
        const facts = factsByRow.get(datum.rowKey) ?? []
        facts.push(datum)
        factsByRow.set(datum.rowKey, facts)
    }
    const trends = new Map(
        matrix.rows.map((row) => [
            row.key,
            matrix.columns.map(
                (column) =>
                    getDotMatrixCellCount(matrix.getCell(row.key, column.key), {
                        countOf: dataset.countOf,
                        selectedSeries,
                        aggregateSelection: dataset.aggregateSelection,
                    }) ?? Number.NaN
            ),
        ])
    )
    return {
        isProducts,
        isDetail,
        displayed,
        series: dataset.series?.map((item, index) => ({
            ...item,
            color: colorMode === 'product' && isProducts ? DOT_MATRIX_MOCK_PRODUCTS[index]?.[2] : undefined,
        })),
        trends,
        trendMax: Math.max(12, ...[...trends.values()].flat().filter(Number.isFinite)),
        rowPeople: new Map([...factsByRow].map(([rowKey, facts]) => [rowKey, getDotMatrixMockPeople(facts)])),
        accountMeta: new Map(
            DOT_MATRIX_MOCK_ACCOUNTS.map((account) => [
                account.id,
                getDotMatrixAccountMeta(account, dataset.data, selectedSeries),
            ])
        ),
        activePeopleCount: getDotMatrixMockPeople(dataset.data.filter((datum) => datum.rowKey === activeAccount))
            .length,
    }
}
