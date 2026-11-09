import { useMemo } from 'react'

import { type Series, StackedBarList } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import type { NewsChartItemApi } from 'products/today/frontend/generated/api.schemas'

import { useTodayTonePalette } from './todayTone'

const STORY_ROWS = 4

function compact(value: number): string {
    const abs = Math.abs(value)
    if (abs >= 1_000_000) {
        return `${Math.round(value / 100_000) / 10}M`
    }
    if (abs >= 10_000) {
        return `${Math.round(value / 100) / 10}k`
    }
    return value.toLocaleString('en-US', { maximumFractionDigits: abs >= 100 ? 0 : abs >= 10 ? 1 : 2 })
}

export function TodayNewsGroupedBarsChart({
    items,
    higherIsGood,
    size,
}: {
    items: NewsChartItemApi[]
    higherIsGood: boolean | null
    size: 'lead' | 'story'
}): JSX.Element {
    const theme = useChartTheme()
    const palette = useTodayTonePalette()
    const rows = useMemo(
        () =>
            (size === 'lead' ? items : items.slice(0, STORY_ROWS)).map((item) => ({
                label: item.label,
                before: item.before ?? 0,
                value: item.value,
            })),
        [items, size]
    )
    const series = useMemo<Series[]>(() => {
        const riseColor = higherIsGood === null ? palette.neutral : higherIsGood ? palette.good : palette.risk
        const fallColor = higherIsGood === null ? palette.line : higherIsGood ? palette.risk : palette.good
        const track = rows.map((row) => Math.max(row.value, row.before))
        const rose = (row: (typeof rows)[number]): boolean => row.value >= row.before
        return [
            {
                key: 'before',
                label: 'Before',
                data: rows.map((row) => (rose(row) ? row.before : 0)),
                trackData: track,
                color: palette.line,
            },
            {
                key: 'up',
                label: 'Up',
                data: rows.map((row) => (rose(row) ? row.value - row.before : 0)),
                trackData: track,
                color: riseColor,
            },
            {
                key: 'down',
                label: 'Down',
                data: rows.map((row) => (rose(row) ? 0 : row.value)),
                trackData: track,
                color: fallColor,
            },
        ]
    }, [rows, palette, higherIsGood])

    return (
        <StackedBarList
            labels={rows.map((row) => row.label)}
            series={series}
            theme={theme}
            config={{
                labelPosition: 'top',
                rowHeight: 34,
                barHeight: 6,
                tooltip: { enabled: false },
                valueDomain: { min: 0, max: Math.max(1, ...rows.map((row) => Math.max(row.value, row.before))) },
            }}
            renderLabel={(row) => <span className="truncate">{rows[row].label}</span>}
            renderValue={(row) => `${compact(rows[row].before)} → ${compact(rows[row].value)}`}
        />
    )
}
