import type { BookActivityMatrixResult } from '~/queries/schema/schema-general'

export function getActivitySelectionMask(series: BookActivityMatrixResult['series'], selected: string[]): number {
    return series.reduce((mask, item, index) => (selected.includes(item.key) ? mask | (2 ** index) : mask), 0)
}

export function getActivityCombinationUsers(
    combination: BookActivityMatrixResult['combinations'][number],
    selectionMask: number
): number {
    return combination.mask & selectionMask ? combination.users : 0
}
