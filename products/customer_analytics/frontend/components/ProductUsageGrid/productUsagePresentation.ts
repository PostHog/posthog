import type { DotMatrixCountBin, DotMatrixGroup, DotMatrixSeries } from 'lib/components/DotMatrix/types'
import { dayjs } from 'lib/dayjs'

import type {
    BookActivityInterval,
    BookActivityMatrixFirstUse,
    BookActivityMatrixGrouping,
    BookActivityMatrixProduct,
} from '~/queries/schema/schema-general'

export function getProductUsageGrouping(
    products: BookActivityMatrixProduct[],
    groupings: BookActivityMatrixGrouping[],
    groupingKey: string
): { series: DotMatrixSeries[]; groups: DotMatrixGroup[]; columnsPerGroup: number } {
    const grouping = groupings.find(({ key }) => key === groupingKey) ?? groupings[0]
    const productKeys = new Set(products.map(({ key }) => key))
    const groups: DotMatrixGroup[] = (grouping?.groups ?? []).map((group, index) => ({
        ...group,
        items: [...new Set(group.items)].filter((key) => productKeys.has(key)),
        color:
            grouping?.key === 'role' && index < 3
                ? ['var(--color-blue-500)', 'var(--color-orange-500)', 'var(--color-purple-500)'][index]
                : `var(--data-color-${(index % 15) + 1})`,
    }))
    const assigned = new Set(groups.flatMap(({ items }) => items ?? []))
    const remaining = products.filter(({ key }) => !assigned.has(key)).map(({ key }) => key)
    if (remaining.length) {
        groups.push({
            key: 'additional',
            label: 'Additional products',
            items: remaining,
            color: 'var(--color-text-secondary)',
        })
    }
    const roles = grouping?.key === 'role'
    return {
        groups,
        columnsPerGroup: roles ? 6 : 5,
        series: products.map((product, index) => ({
            ...product,
            group: groups.find(({ items }) => items?.includes(product.key))?.key,
            color: roles
                ? groups.find(({ items }) => items?.includes(product.key))?.color
                : index < 15
                  ? `var(--data-color-${index + 1})`
                  : `color-mix(in srgb, var(--data-color-${(index % 15) + 1}) 60%, var(--color-text-primary))`,
        })),
    }
}

export function getProductUsageFirstSeries(
    firstUse: BookActivityMatrixFirstUse[],
    rowKey: string,
    columnKey: string,
    interval: BookActivityInterval
): string[] {
    const end = dayjs(columnKey).add(1, interval).format('YYYY-MM-DD')
    return firstUse
        .filter(({ row, date }) => row === rowKey && date >= columnKey.slice(0, 10) && date < end)
        .map(({ series }) => series)
}

export function getProductUsageCountLabel(products: BookActivityMatrixProduct[], selected: string[]): string {
    return selected.length === 0
        ? 'Products used'
        : selected.length === 1
          ? `Users of ${products.find(({ key }) => key === selected[0])?.label ?? selected[0]}`
          : `Users of any of these ${selected.length} products`
}

export function getProductUsageCountScale(users = false): DotMatrixCountBin[] {
    const steps = users ? [1, 2, 5, 10, 20, 50] : [1, 3, 5, 7, 9, 11]
    const color = users ? 'var(--color-blue-700)' : 'var(--color-green-700)'
    return steps.map((min, index) => ({
        min,
        color: `color-mix(in srgb, ${color} ${15 + index * 15}%, var(--color-bg-surface-primary))`,
        ink: index >= 4 ? 'var(--color-white)' : 'var(--color-text-primary)',
    }))
}
