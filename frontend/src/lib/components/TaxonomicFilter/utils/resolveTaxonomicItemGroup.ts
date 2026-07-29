import { hasRecentContext } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { hasPinnedContext } from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

export function getTaxonomicItemSourceGroupType(
    item: TaxonomicDefinitionTypes | undefined
): TaxonomicFilterGroupType | undefined {
    if (hasRecentContext(item)) {
        return item._recentContext.sourceGroupType
    }
    if (hasPinnedContext(item)) {
        return item._pinnedContext.sourceGroupType
    }
    if (item && typeof item === 'object' && 'group' in item) {
        return item.group as TaxonomicFilterGroupType
    }
    return undefined
}

export function resolveTaxonomicItemGroup(
    item: TaxonomicDefinitionTypes | undefined,
    groups: TaxonomicFilterGroup[],
    defaultGroup: TaxonomicFilterGroup | undefined
): TaxonomicFilterGroup | undefined {
    const declaredGroupType = getTaxonomicItemSourceGroupType(item) ?? defaultGroup?.type
    const declaredGroup = groups.find((group) => group.type === declaredGroupType) ?? defaultGroup
    return groups.find((group) => group.type === declaredGroup?.sourceGroupType) ?? declaredGroup
}

export function getTaxonomicItemValue(
    item: TaxonomicDefinitionTypes,
    sourceGroup: TaxonomicFilterGroup
): TaxonomicFilterValue | null {
    if (hasRecentContext(item)) {
        return item._recentContext.sourceValue ?? sourceGroup.getValue?.(item) ?? null
    }
    if (hasPinnedContext(item)) {
        return item._pinnedContext.value ?? sourceGroup.getValue?.(item) ?? null
    }
    return sourceGroup.getValue?.(item) ?? null
}

export function resolveTaxonomicDisplayGroup(
    item: TaxonomicDefinitionTypes,
    groups: TaxonomicFilterGroup[],
    sourceGroup: TaxonomicFilterGroup
): TaxonomicFilterGroup {
    const sourceValue = getTaxonomicItemValue(item, sourceGroup)
    if (sourceValue != null) {
        const curatedGroup = groups.find(
            (group) =>
                group.sourceGroupType === sourceGroup.type &&
                group.options?.some((option) => sourceGroup.getValue?.(option) === sourceValue)
        )
        if (curatedGroup) {
            return curatedGroup
        }
    }
    return groups.find((group) => group.type === sourceGroup.type) ?? sourceGroup
}
