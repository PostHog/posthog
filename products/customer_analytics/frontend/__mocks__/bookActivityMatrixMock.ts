import type {
    BookActivityMatrixCell,
    BookActivityMatrixGrouping,
    BookActivityMatrixCombination,
    BookActivityMatrixFirstUse,
    BookActivityMatrixResult,
} from '~/queries/schema/schema-general'

const GROUPINGS: BookActivityMatrixGrouping[] = [
    {
        key: 'role',
        label: 'Roles',
        groups: [
            {
                key: 'product_cs',
                label: 'Product & CS',
                items: ['pa', 'web', 'replay', 'surveys', 'customers', 'workflows'],
            },
            { key: 'engineering', label: 'Engineering', items: ['flags', 'exp', 'errors', 'logs', 'tracing', 'sd'] },
            { key: 'data_ai', label: 'Data & AI', items: ['dwh', 'pipelines', 'endpoints', 'llm', 'mcpa', 'ai'] },
        ],
    },
    {
        key: 'usecase',
        label: 'Use cases',
        groups: [
            {
                key: 'product_intelligence',
                label: 'Product Intelligence',
                items: ['pa', 'replay', 'heatmaps', 'surveys', 'ai'],
            },
            { key: 'release_engineering', label: 'Release Engineering', items: ['flags', 'exp', 'sd'] },
            { key: 'observability', label: 'Observability', items: ['errors', 'logs', 'tracing'] },
            {
                key: 'growth_marketing',
                label: 'Growth & Marketing',
                items: ['web', 'heatmaps', 'surveys', 'workflows', 'pipelines'],
            },
            { key: 'ai_llm_observability', label: 'AI/LLM Observability', items: ['llm', 'mcpa', 'ai', 'sd'] },
            {
                key: 'data_infrastructure',
                label: 'Data Infrastructure',
                items: ['dwh', 'pipelines', 'endpoints', 'semantic'],
            },
            {
                key: 'customer_experience',
                label: 'Customer Experience',
                items: ['support', 'replay', 'errors', 'surveys', 'workflows'],
            },
        ],
    },
]

const PRODUCTS: [key: string, label: string][] = [
    ['pa', 'Product analytics'],
    ['web', 'Web analytics'],
    ['replay', 'Session replay'],
    ['heatmaps', 'Heatmaps'],
    ['surveys', 'Surveys'],
    ['customers', 'Customer analytics'],
    ['flags', 'Feature flags'],
    ['exp', 'Experiments'],
    ['errors', 'Error tracking'],
    ['logs', 'Logs'],
    ['tracing', 'Tracing & metrics'],
    ['workflows', 'Workflows'],
    ['dwh', 'Data warehouse'],
    ['endpoints', 'Endpoints'],
    ['pipelines', 'Data pipelines'],
    ['llm', 'AI observability'],
    ['mcpa', 'MCP analytics'],
    ['ai', 'PostHog AI'],
    ['support', 'Support'],
    ['sd', 'Self-driving'],
    ['semantic', 'Semantic layer'],
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
    groupings: GROUPINGS,
    series: PRODUCTS.map(([key, label]) => ({ key, label })),
    data,
    combinations,
    firstUse,
    truncated: false,
}
