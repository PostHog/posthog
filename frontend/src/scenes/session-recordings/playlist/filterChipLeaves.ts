import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

import { UniversalFilterValue, UniversalFiltersGroup } from '~/types'

export interface FilterLeaf {
    /** Indexes into nested `values` arrays, from the root group down to the leaf. */
    path: number[]
    filter: UniversalFilterValue
}

export function filterLeaves(group: UniversalFiltersGroup, path: number[] = []): FilterLeaf[] {
    return group.values.flatMap((value, index) =>
        isUniversalGroupFilterLike(value)
            ? filterLeaves(value, [...path, index])
            : [{ path: [...path, index], filter: value }]
    )
}

/** The group tree without the leaf at `path`. A group that empties stays, so the editor's structure is kept. */
export function removeFilterLeaf(group: UniversalFiltersGroup, path: number[]): UniversalFiltersGroup {
    const [index, ...rest] = path
    return {
        ...group,
        values: group.values.flatMap((value, i) => {
            if (i !== index) {
                return [value]
            }
            if (rest.length === 0 || !isUniversalGroupFilterLike(value)) {
                return []
            }
            return [removeFilterLeaf(value, rest)]
        }),
    }
}
