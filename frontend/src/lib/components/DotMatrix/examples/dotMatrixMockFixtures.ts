import './mocks.scss'

import type { DotMatrixCountBin } from '../types'
import type { DotMatrixMockAccount } from './dotMatrixMockTypes'

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
export const PERSON_NAMES = [
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
export const ROSTERS: Record<string, string[]> = {
    acme: PERSON_NAMES,
    globex: ['kim', 'alex', 'rosa', 'theo', 'lin'],
}
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
    ink:
        index === 3
            ? 'var(--dot-matrix-demo-green-4-ink)'
            : index === 4
              ? 'var(--dot-matrix-demo-green-5-ink)'
              : index === 5
                ? 'var(--dot-matrix-demo-green-ink)'
                : 'var(--dot-matrix-demo-count-ink)',
    label: ['1-2', '3-4', '5-6', '7-8', '9-10', '11+'][index],
}))
export const DOT_MATRIX_USER_COUNT_SCALE: DotMatrixCountBin[] = [1, 2, 5, 10, 20, 50].map((min, index) => ({
    min,
    color: `var(--dot-matrix-demo-blue-${index + 1})`,
    ink:
        index === 4
            ? 'var(--dot-matrix-demo-blue-5-ink)'
            : index === 5
              ? 'var(--dot-matrix-demo-blue-ink)'
              : 'var(--dot-matrix-demo-count-ink)',
    label: ['1', '2-4', '5-9', '10-19', '20-49', '50+'][index],
}))
