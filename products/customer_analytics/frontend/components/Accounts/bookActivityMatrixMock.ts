import type {
    BookActivityMatrixCell,
    BookActivityMatrixCombination,
    BookActivityMatrixFirstUse,
    BookActivityMatrixResult,
} from '~/queries/schema/schema-general'

const FAMILIES = [
    { key: 'product_cs', label: 'Product & CS' },
    { key: 'engineering', label: 'Engineering' },
    { key: 'data_ai', label: 'Data & AI' },
]

const PRODUCTS: [key: string, label: string, family: string][] = [
    ['product_analytics', 'Product analytics', 'product_cs'],
    ['web_analytics', 'Web analytics', 'product_cs'],
    ['session_replay', 'Session replay', 'product_cs'],
    ['surveys', 'Surveys', 'product_cs'],
    ['customer_analytics', 'Customer analytics', 'product_cs'],
    ['workflows', 'Workflows', 'product_cs'],
    ['feature_flags', 'Feature flags', 'engineering'],
    ['experiments', 'Experiments', 'engineering'],
    ['error_tracking', 'Error tracking', 'engineering'],
    ['logs', 'Logs', 'engineering'],
    ['tracing', 'Tracing & metrics', 'engineering'],
    ['inbox', 'Self-driving inbox', 'engineering'],
    ['data_warehouse', 'Data warehouse', 'data_ai'],
    ['data_pipelines', 'Data pipelines', 'data_ai'],
    ['endpoints', 'Endpoints', 'data_ai'],
    ['ai_observability', 'AI observability', 'data_ai'],
    ['mcp_analytics', 'MCP analytics', 'data_ai'],
    ['posthog_ai', 'PostHog AI', 'data_ai'],
]

const ACCOUNTS: [key: string, label: string, externalId: string][] = [
    ['account-acme', 'Acme Robotics', 'org-acme'],
    ['account-globex', 'Globex', 'org-globex'],
    ['account-initech', 'Initech', 'org-initech'],
    ['account-hooli', 'Hooli', 'org-hooli'],
    ['account-northwind', 'Northwind', 'org-northwind'],
    ['account-umbrella', 'Umbrella Health', 'org-umbrella'],
]

const WEEKS = Array.from({ length: 13 }, (_, index) => {
    const day = new Date(Date.UTC(2026, 7, 2 + index * 7))
    return day.toISOString().slice(0, 10)
})

function combinationsFor(accountIndex: number, weekIndex: number): { mask: number; users: number }[] {
    const groups = 2 + ((accountIndex + weekIndex) % 4)
    return Array.from({ length: groups }, (_, groupIndex) => {
        let mask = 0
        PRODUCTS.forEach((_, productIndex) => {
            if ((accountIndex * 5 + weekIndex + productIndex * 3 + groupIndex * 7) % 9 < 2) {
                mask |= 1 << productIndex
            }
        })
        return { mask: mask || 1, users: 1 + ((accountIndex + groupIndex * 3 + weekIndex) % 6) }
    }).filter((combination, index, all) => all.findIndex(({ mask }) => mask === combination.mask) === index)
}

const combinations: BookActivityMatrixCombination[] = ACCOUNTS.flatMap(([row], accountIndex) =>
    WEEKS.flatMap((column, weekIndex) =>
        combinationsFor(accountIndex, weekIndex).map(({ mask, users }) => ({ row, column, mask, users }))
    )
)

const data: BookActivityMatrixCell[] = ACCOUNTS.flatMap(([row]) =>
    WEEKS.flatMap((column) =>
        PRODUCTS.map(([series], productIndex) => ({
            row,
            column,
            series,
            users: combinations
                .filter((combination) => combination.row === row && combination.column === column)
                .filter(({ mask }) => mask & (1 << productIndex))
                .reduce((total, { users }) => total + users, 0),
        })).filter(({ users }) => users > 0)
    )
)

const firstUse: BookActivityMatrixFirstUse[] = ACCOUNTS.flatMap(([row]) =>
    PRODUCTS.flatMap(([series]) => {
        const first = data.find((cell) => cell.row === row && cell.series === series)
        return first ? [{ row, series, date: first.column }] : []
    })
)

export const BOOK_ACTIVITY_MATRIX_MOCK: BookActivityMatrixResult = {
    rows: ACCOUNTS.map(([key, label, externalId]) => ({ key, label, externalId })),
    columns: WEEKS.map((key, index) => ({ key, partial: index === WEEKS.length - 1 })),
    families: FAMILIES,
    series: PRODUCTS.map(([key, label, family]) => ({ key, label, family, useCase: null })),
    data,
    combinations,
    firstUse,
    truncated: false,
}
