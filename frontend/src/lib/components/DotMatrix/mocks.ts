import './mocks.scss'

import type { DotMatrixAxisItem, DotMatrixCell, DotMatrixCountBin, DotMatrixProps } from './types'

export type DotMatrixMockDatasetName = 'product_activity' | 'people' | 'ci'
export interface DotMatrixMockPerson {
    id: string
    name: string
    email: string
    seconds: number
}
export interface DotMatrixMockDatum extends Record<string, unknown> {
    rowKey: string
    columnKey: string
    seriesKey: string
    value: number
    persons: DotMatrixMockPerson[]
}
export interface DotMatrixMockAccount {
    id: string
    name: string
    logo: string
    u: Record<string, number[]>
}
export type DotMatrixMockDataset = DotMatrixProps<DotMatrixMockDatum>

export const DOT_MATRIX_MOCK_PRODUCTS: [string, string, string][] = [
    ['pa', 'Product analytics', '#259dfb'],
    ['web', 'Web analytics', '#40c1bd'],
    ['replay', 'Session replay', '#fe843d'],
    ['heatmaps', 'Heatmaps', '#baae31'],
    ['surveys', 'Surveys', '#eb76e9'],
    ['customers', 'Customer analytics', '#ba7d3e'],
    ['flags', 'Feature flags', '#47c94e'],
    ['exp', 'Experiments', '#9464ee'],
    ['errors', 'Error tracking', '#f4543a'],
    ['logs', 'Logs', '#3e9dca'],
    ['tracing', 'Tracing and metrics', '#b46a96'],
    ['workflows', 'Workflows', '#f85581'],
    ['dwh', 'Data warehouse', '#4076f5'],
    ['endpoints', 'Endpoints', '#539f6a'],
    ['pipelines', 'Data pipelines', '#a2822a'],
    ['llm', 'LLM analytics', '#c068ac'],
    ['mcpa', 'MCP analytics', '#529c20'],
    ['ai', 'PostHog AI', '#a7a0ec'],
]
export const DOT_MATRIX_MOCK_ACCOUNTS: DotMatrixMockAccount[] = [
    {
        id: 'acme',
        name: 'Acme Robotics',
        logo: '#4f46e5',
        u: {
            pa: [12, 13, 15, 14, 13, 15, 14, 7],
            web: [3, 4, 3, 4, 3, 4, 4, 2],
            replay: [6, 7, 6, 8, 9, 10, 11, 5],
            heatmaps: [1, 0, 2, 0, 1, 0, 2, 0],
            surveys: [2, 2, 1, 2, 2, 2, 1, 0],
            flags: [5, 6, 6, 5, 6, 6, 5, 3],
            exp: [0, 0, 0, 1, 2, 3, 3, 2],
            errors: [4, 5, 4, 5, 4, 4, 5, 2],
            dwh: [2, 3, 2, 3, 3, 2, 3, 1],
            ai: [3, 4, 4, 5, 5, 6, 6, 3],
        },
    },
    {
        id: 'globex',
        name: 'Globex',
        logo: '#0284c7',
        u: { pa: [4, 3, 4, 4, 3, 3, 2, 1], replay: [2, 1, 2, 1, 1, 1, 0, 0], flags: [1, 1, 1, 1, 1, 0, 1, 0] },
    },
    {
        id: 'initech',
        name: 'Initech',
        logo: '#ea580c',
        u: {
            pa: [7, 6, 7, 6, 7, 6, 6, 3],
            replay: [10, 9, 7, 5, 3, 2, 1, 0],
            errors: [2, 3, 2, 3, 2, 3, 3, 1],
            logs: [0, 0, 1, 1, 2, 1, 2, 1],
            llm: [0, 0, 0, 0, 2, 3, 3, 1],
        },
    },
    {
        id: 'hooli',
        name: 'Hooli',
        logo: '#dc2626',
        u: {
            pa: [5, 5, 6, 5, 5, 6, 5, 2],
            flags: [11, 12, 13, 12, 12, 13, 12, 6],
            exp: [4, 5, 6, 5, 4, 6, 5, 2],
            errors: [7, 8, 9, 8, 7, 9, 8, 4],
            logs: [3, 4, 3, 4, 3, 4, 4, 2],
            tracing: [1, 2, 1, 2, 2, 1, 2, 1],
            endpoints: [1, 1, 2, 1, 2, 2, 1, 1],
            pipelines: [1, 0, 1, 1, 0, 1, 1, 0],
            dwh: [4, 5, 4, 5, 5, 4, 5, 2],
        },
    },
    {
        id: 'northwind',
        name: 'Northwind',
        logo: '#059669',
        u: {
            pa: [4, 4, 3, 4, 4, 4, 3, 2],
            web: [5, 6, 5, 6, 6, 5, 6, 3],
            replay: [3, 3, 2, 3, 3, 3, 2, 1],
            heatmaps: [2, 2, 1, 2, 2, 2, 2, 1],
            surveys: [3, 3, 3, 2, 3, 3, 3, 1],
            customers: [1, 1, 0, 1, 1, 1, 1, 0],
            workflows: [0, 0, 2, 2, 3, 2, 3, 1],
        },
    },
    {
        id: 'vandelay',
        name: 'Vandelay Industries',
        logo: '#9333ea',
        u: {
            pa: [3, 3, 3, 2, 3, 3, 3, 1],
            errors: [1, 1, 0, 1, 1, 1, 1, 0],
            dwh: [2, 2, 2, 2, 2, 2, 2, 1],
            llm: [6, 7, 7, 8, 7, 8, 8, 4],
            mcpa: [1, 1, 2, 1, 2, 2, 2, 1],
            ai: [4, 4, 5, 4, 5, 5, 5, 2],
        },
    },
    {
        id: 'umbrella',
        name: 'Umbrella Health',
        logo: '#be123c',
        u: {
            pa: [8, 9, 8, 9, 10, 9, 9, 4],
            replay: [4, 5, 5, 6, 5, 6, 6, 3],
            surveys: [1, 1, 2, 2, 1, 2, 2, 1],
            customers: [2, 2, 2, 3, 3, 3, 3, 1],
            flags: [2, 2, 3, 2, 3, 3, 2, 1],
            errors: [3, 3, 4, 3, 3, 4, 4, 2],
        },
    },
    {
        id: 'stark',
        name: 'Stark Logistics',
        logo: '#475569',
        u: { pa: [2, 2, 1, 2, 1, 1, 1, 0], web: [1, 1, 1, 0, 1, 0, 0, 0] },
    },
    {
        id: 'cyberdyne',
        name: 'Cyberdyne',
        logo: '#0e7490',
        u: {
            pa: [6, 6, 7, 6, 6, 7, 6, 3],
            flags: [6, 7, 7, 6, 7, 8, 7, 3],
            exp: [2, 2, 3, 2, 3, 3, 2, 1],
            errors: [5, 5, 6, 5, 6, 6, 5, 2],
            logs: [2, 3, 3, 4, 4, 5, 5, 2],
            tracing: [1, 1, 2, 2, 3, 3, 4, 2],
            dwh: [3, 3, 3, 3, 3, 3, 3, 1],
            llm: [2, 2, 3, 3, 3, 4, 4, 2],
            ai: [2, 3, 3, 3, 4, 4, 4, 2],
        },
    },
    {
        id: 'wonka',
        name: 'Wonka Labs',
        logo: '#b45309',
        u: {
            pa: [5, 5, 5, 6, 5, 5, 6, 2],
            web: [4, 4, 5, 4, 5, 5, 4, 2],
            heatmaps: [1, 2, 1, 2, 2, 1, 2, 1],
            surveys: [2, 2, 2, 2, 3, 2, 2, 1],
            workflows: [3, 3, 4, 4, 4, 5, 5, 2],
            dwh: [1, 1, 1, 1, 2, 2, 2, 1],
            pipelines: [1, 1, 1, 1, 1, 1, 1, 0],
        },
    },
]
const ROSTERS: Record<string, string[]> = {
    acme: [
        'dana',
        'priya',
        'sam',
        'lee',
        'omar',
        'jules',
        'kim',
        'ravi',
        'ana',
        'tom',
        'mei',
        'felix',
        'nora',
        'ben',
        'zoe',
        'ivan',
    ],
    globex: ['kim', 'alex', 'rosa', 'theo', 'lin'],
}
const PERSON_NAMES = [
    'dana',
    'priya',
    'sam',
    'lee',
    'omar',
    'jules',
    'kim',
    'ravi',
    'ana',
    'tom',
    'mei',
    'felix',
    'nora',
    'ben',
    'zoe',
    'ivan',
]
export const DOT_MATRIX_MOCK_GROUPS = [
    { key: 'understand', label: 'Understand', color: '#3b82f6' },
    { key: 'ship', label: 'Ship and fix', color: '#d97328' },
    { key: 'data', label: 'Data and AI', color: '#c24fa0' },
]
export const DOT_MATRIX_MOCK_COLUMNS = [
    'Sep 14',
    'Sep 21',
    'Sep 28',
    'Oct 5',
    'Oct 12',
    'Oct 19',
    'Oct 26',
    'Nov 2',
].map((label, index) => ({ key: `week-${index}`, label, partial: index === 7 }))

export function getDotMatrixMockWeekLabel(columnKey: string): string {
    const index = DOT_MATRIX_MOCK_COLUMNS.findIndex((column) => column.key === columnKey)
    const column = DOT_MATRIX_MOCK_COLUMNS[index]
    if (!column) {
        return columnKey
    }
    const end = ['Sep 20', 'Sep 27', 'Oct 4', 'Oct 11', 'Oct 18', 'Oct 25', 'Nov 1'][index]
    return `Week of ${column.label}${column.partial ? ' to date' : ` to ${end}`}`
}

export const DOT_MATRIX_PRODUCT_COUNT_SCALE: DotMatrixCountBin[] = [1, 3, 5, 7, 9, 11].map((min, index) => ({
    min,
    color: `var(--dot-matrix-demo-green-${index + 1})`,
    ink: index >= 4 ? 'var(--dot-matrix-demo-green-ink)' : 'var(--dot-matrix-demo-count-ink)',
    label: ['1-2', '3-4', '5-6', '7-8', '9-10', '11+'][index],
}))
export const DOT_MATRIX_USER_COUNT_SCALE: DotMatrixCountBin[] = [1, 2, 5, 10, 20, 50].map((min, index) => ({
    min,
    color: `var(--dot-matrix-demo-blue-${index + 1})`,
    ink: index >= 4 ? 'var(--dot-matrix-demo-blue-ink)' : 'var(--dot-matrix-demo-count-ink)',
    label: ['1', '2-4', '5-9', '10-19', '20-49', '50+'][index],
}))

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

export function aggregateDotMatrixMockPeople(cell: DotMatrixCell<DotMatrixMockDatum>, selected: string[]): number {
    const keys = new Set(selected)
    return new Set(
        cell.data
            .filter((datum) => datum.value > 0 && (keys.size === 0 || keys.has(datum.seriesKey)))
            .flatMap((datum) => datum.persons.map((person) => person.id))
    ).size
}

export function getDotMatrixMockDataset(name: DotMatrixMockDatasetName): DotMatrixMockDataset {
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
            countScale: DOT_MATRIX_PRODUCT_COUNT_SCALE,
            legend: { itemLabel: 'job', valueLabel: 'Failures', countLabel: 'Failing jobs' },
        }
    }
    const series = DOT_MATRIX_MOCK_PRODUCTS.map(([key, label], index) => ({
        key,
        label,
        group: DOT_MATRIX_MOCK_GROUPS[Math.floor(index / 6)].key,
    }))
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
            countScale: DOT_MATRIX_PRODUCT_COUNT_SCALE,
            legend: { itemLabel: 'product', valueLabel: 'Events', countLabel: 'Products used' },
        }
    }
    return {
        data: accountData,
        fields,
        rows: DOT_MATRIX_MOCK_ACCOUNTS.map((account) => ({ key: account.id, label: account.name })),
        columns: DOT_MATRIX_MOCK_COLUMNS,
        series,
        groups: DOT_MATRIX_MOCK_GROUPS,
        rowHeader: { title: 'Account' },
        aggregateSelection: aggregateDotMatrixMockPeople,
        countScale: DOT_MATRIX_PRODUCT_COUNT_SCALE,
        legend: { itemLabel: 'product', valueLabel: 'Users', countLabel: 'Products used' },
    }
}

export function getDotMatrixAccountMeta(
    account: DotMatrixMockAccount,
    data: DotMatrixMockDatum[],
    selected: string[]
): string {
    if (selected.length > 0) {
        const people = new Set(
            data
                .filter((datum) => datum.rowKey === account.id && selected.includes(datum.seriesKey))
                .flatMap((datum) => datum.persons.map((person) => person.id))
        )
        const productLabel =
            selected.length === 1
                ? DOT_MATRIX_MOCK_PRODUCTS.find(([key]) => key === selected[0])?.[1]
                : `these ${selected.length} products`
        return people.size ? `${people.size} users of ${productLabel}` : 'No use in range'
    }
    const products = Object.values(account.u).filter((values) => values.some((value) => value > 0)).length
    const people = Math.max(0, ...Object.values(account.u).flat()) + products
    return `${products} products · ${people} users`
}

export function getDotMatrixDetailDataset(
    data: DotMatrixMockDatum[],
    selected: string[],
    accountOnly = false,
    selectedAccount = 'acme'
): DotMatrixMockDataset {
    const accounts = accountOnly
        ? DOT_MATRIX_MOCK_ACCOUNTS.filter((account) => account.id === selectedAccount)
        : DOT_MATRIX_MOCK_ACCOUNTS.slice(0, 2)
    const rows: DotMatrixAxisItem[] = []
    const result: DotMatrixMockDatum[] = []
    for (const account of accounts) {
        if (accountOnly) {
            rows.push({ key: 'summary', label: 'Products used', group: 'summary' })
            for (const column of DOT_MATRIX_MOCK_COLUMNS) {
                result.push({
                    rowKey: 'summary',
                    columnKey: column.key,
                    seriesKey: '',
                    value: data.filter(
                        (datum) => datum.rowKey === account.id && datum.columnKey === column.key && datum.value > 0
                    ).length,
                    persons: [],
                })
            }
        }
        if (!accountOnly) {
            rows.push({ key: account.id, label: account.name, group: 'account' })
            for (const column of DOT_MATRIX_MOCK_COLUMNS) {
                const cellData = data.filter((datum) => datum.rowKey === account.id && datum.columnKey === column.key)
                result.push({
                    rowKey: account.id,
                    columnKey: column.key,
                    seriesKey: '',
                    value: selected.length
                        ? aggregateDotMatrixMockPeople(
                              { rowKey: account.id, columnKey: column.key, values: {}, data: cellData },
                              selected
                          )
                        : cellData.filter((datum) => datum.value > 0).length,
                    persons: [],
                })
            }
        }
        DOT_MATRIX_MOCK_GROUPS.forEach((group, groupIndex) => {
            const products = DOT_MATRIX_MOCK_PRODUCTS.slice(groupIndex * 6, groupIndex * 6 + 6).filter(
                ([product]) =>
                    account.u[product]?.some((value) => value > 0) && (!selected.length || selected.includes(product))
            )
            if (accountOnly && products.length) {
                rows.push({ key: `group:${group.key}`, label: group.label, group: 'family' })
            }
            for (const [product, label] of products) {
                const rowKey = `${account.id}/${product}`
                rows.push({ key: rowKey, label, group: group.key })
                result.push(
                    ...data
                        .filter((datum) => datum.rowKey === account.id && datum.seriesKey === product)
                        .map((datum) => ({ ...datum, rowKey, seriesKey: '' }))
                )
            }
        })
    }
    return {
        data: result,
        fields: { row: 'rowKey', column: 'columnKey', value: 'value' },
        rows,
        columns: DOT_MATRIX_MOCK_COLUMNS,
        mode: 'count',
        countOf: 'value',
        countScale: DOT_MATRIX_USER_COUNT_SCALE,
        legend: false,
        rowHeader: { title: accountOnly ? 'Product' : 'Account and product' },
        cellWidth: accountOnly ? 64 : 110,
    }
}
