import { isEmptyProperty } from 'lib/components/PropertyFilters/utils'

import { AnyPropertyFilter, FeatureFlagGroupType, PropertyFilterType } from '~/types'

export type UnfinishedFilterPositions = number[][]

function isUnfinishedFilter(property: AnyPropertyFilter): boolean {
    return !!property.key && property.type !== PropertyFilterType.HogQL && isEmptyProperty(property)
}

function filterIdentity(property: AnyPropertyFilter): string {
    return `${property.type}:${property.key}`
}

// A row with a property picked but no value filters nothing yet, so a save can drop it. Two kinds
// stay on the flag and block the save, because dropping them would make the flag match more
// people: a row whose property the saved flag already filters on (its value can be cleared), and
// a row that is the last filter left in its condition set.
export function findDroppableFilters(
    groups: FeatureFlagGroupType[] | undefined,
    savedGroups: FeatureFlagGroupType[] | undefined
): UnfinishedFilterPositions {
    const savedFilters = new Set((savedGroups ?? []).flatMap((group) => (group.properties ?? []).map(filterIdentity)))
    return (groups ?? []).map(({ properties = [] }) => {
        const droppable = properties.flatMap((property, index) =>
            isUnfinishedFilter(property) && !savedFilters.has(filterIdentity(property)) ? [index] : []
        )
        return droppable.length < properties.length ? droppable : []
    })
}

export function withoutFilters(
    groups: FeatureFlagGroupType[],
    positions: UnfinishedFilterPositions
): FeatureFlagGroupType[] {
    return groups.map((group, groupIndex) => {
        const drop = positions[groupIndex]
        if (!drop?.length) {
            return group
        }
        return { ...group, properties: group.properties?.filter((_, index) => !drop.includes(index)) }
    })
}
