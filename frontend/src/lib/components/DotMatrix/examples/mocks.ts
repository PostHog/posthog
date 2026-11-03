import type { DotMatrixCell } from '../types'
import { getDotMatrixDemoPresentation } from './dotMatrixDemoPresentation'
import {
    DOT_MATRIX_MOCK_ACCOUNTS,
    DOT_MATRIX_MOCK_COLUMNS,
    DOT_MATRIX_MOCK_GROUPS,
    DOT_MATRIX_MOCK_PRODUCTS,
    PERSON_NAMES,
    ROSTERS,
} from './dotMatrixMockFixtures'
import type {
    DotMatrixMockAccount,
    DotMatrixMockDataset,
    DotMatrixMockDatasetName,
    DotMatrixMockDatum,
    DotMatrixMockPerson,
} from './dotMatrixMockTypes'

function peopleFor(account: DotMatrixMockAccount, productIndex: number, count: number): DotMatrixMockPerson[] {
    const roster = ROSTERS[account.id] ?? PERSON_NAMES
    const offset = (productIndex * 5) % roster.length
    const ordered = [...roster.slice(offset), ...roster.slice(0, offset)]
    return Array.from({ length: count }, (_, index) => {
        const name = ordered[index % ordered.length]
        const suffix = index >= ordered.length ? String(Math.floor(index / ordered.length) + 1) : ''
        return {
            id: `${account.id}:${name}${suffix}`,
            name: `${name}${suffix}`,
            email: `${name}${suffix}@${account.id}.example`,
            seconds: 872 - index * 31,
        }
    })
}

export function getDotMatrixMockPeople(data: DotMatrixMockDatum[], selected: string[] = []): DotMatrixMockPerson[] {
    const keys = new Set(selected)
    return [
        ...new Map(
            data
                .filter((datum) => datum.value > 0 && (keys.size === 0 || keys.has(datum.seriesKey)))
                .flatMap((datum) => datum.persons.map((person) => [person.id, person] as const))
        ).values(),
    ]
}

export function aggregateDotMatrixMockPeople(cell: DotMatrixCell<DotMatrixMockDatum>, selected: string[]): number {
    return getDotMatrixMockPeople(cell.data, selected).length
}

export function getDotMatrixMockDataset(name: DotMatrixMockDatasetName): DotMatrixMockDataset {
    const { countScale, legend } = getDotMatrixDemoPresentation(name, [])
    const fields = { row: 'rowKey', column: 'columnKey', series: 'seriesKey', value: 'value' } as const
    if (name === 'ci') {
        const series = ['Build', 'Unit tests', 'Typecheck', 'Lint', 'Browser tests', 'Deploy'].map((label, index) => ({
            key: `job-${index}`,
            label,
            group: index < 3 ? 'checks' : 'release',
        }))
        const rows = ['web-app', 'api-service', 'design-system', 'mobile-app', 'worker'].map((key) => ({
            key,
            label: key,
        }))
        const data = rows.flatMap((row, rowIndex) =>
            DOT_MATRIX_MOCK_COLUMNS.flatMap((column, columnIndex) =>
                series.map((item, seriesIndex) => ({
                    rowKey: row.key,
                    columnKey: column.key,
                    seriesKey: item.key,
                    value:
                        (rowIndex * 7 + columnIndex * 3 + seriesIndex * 11) % 17 > 10
                            ? (rowIndex + columnIndex + seriesIndex) % 12
                            : 0,
                    persons: [],
                }))
            )
        )
        return {
            data,
            fields,
            rows,
            columns: DOT_MATRIX_MOCK_COLUMNS,
            series,
            groups: [
                { key: 'checks', label: 'Checks', color: '#3b82f6' },
                { key: 'release', label: 'Release', color: '#d97328' },
            ],
            rowHeader: { title: 'Repository' },
            aggregateSelection: (cell, selected) =>
                Object.entries(cell.values).filter(([key, value]) => value > 0 && selected.includes(key)).length,
            countScale,
            legend,
        }
    }
    const series = DOT_MATRIX_MOCK_PRODUCTS.map(([key, label], index) => ({
        key,
        label,
        group: DOT_MATRIX_MOCK_GROUPS[Math.floor(index / 6)].key,
    }))
    if (name === 'people') {
        const people = peopleFor(DOT_MATRIX_MOCK_ACCOUNTS[0], 0, 8)
        const data = people.flatMap((person, personIndex) =>
            DOT_MATRIX_MOCK_COLUMNS.flatMap((column, week) =>
                series.map((item, seriesIndex) => ({
                    rowKey: person.id,
                    columnKey: column.key,
                    seriesKey: item.key,
                    value:
                        (personIndex * 3 + week + seriesIndex * 7) % 8 < 3
                            ? ((personIndex + week + seriesIndex) % 13) + 1
                            : 0,
                    persons: [person],
                }))
            )
        )
        return {
            data,
            fields,
            rows: people.map((person) => ({ key: person.id, label: person.email })),
            columns: DOT_MATRIX_MOCK_COLUMNS,
            series,
            groups: DOT_MATRIX_MOCK_GROUPS,
            rowHeader: { title: 'Person' },
            aggregateSelection: aggregateDotMatrixMockPeople,
            countScale,
            legend,
        }
    }
    const accountData = DOT_MATRIX_MOCK_ACCOUNTS.flatMap((account) =>
        DOT_MATRIX_MOCK_COLUMNS.flatMap((column, week) =>
            DOT_MATRIX_MOCK_PRODUCTS.map(([product], productIndex) => {
                const value = account.u[product]?.[week] ?? 0
                const persons = peopleFor(account, productIndex, value)
                if (product === 'tracing' && value > 0) {
                    const logs = peopleFor(account, 9, account.u.logs?.[week] ?? 0)
                    const overlap = Math.ceil(value / 2)
                    return {
                        rowKey: account.id,
                        columnKey: column.key,
                        seriesKey: product,
                        value,
                        persons: [
                            ...logs.slice(0, overlap),
                            ...persons
                                .filter((person) => !logs.some((logPerson) => logPerson.id === person.id))
                                .slice(0, value - overlap),
                        ],
                    }
                }
                return { rowKey: account.id, columnKey: column.key, seriesKey: product, value, persons }
            })
        )
    )
    return {
        data: accountData,
        fields,
        rows: DOT_MATRIX_MOCK_ACCOUNTS.map((account) => ({ key: account.id, label: account.name })),
        columns: DOT_MATRIX_MOCK_COLUMNS,
        series,
        groups: DOT_MATRIX_MOCK_GROUPS,
        rowHeader: { title: 'Account' },
        aggregateSelection: aggregateDotMatrixMockPeople,
        countScale,
        legend,
    }
}
