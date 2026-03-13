import { Noun } from '~/models/groupsModel'

export const AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE: Noun = {
    singular: 'entity',
    plural: 'entities',
}

export function getAggregationTargetPronoun(
    aggregationGroupTypeIndex: number | null | undefined,
    customAggregationTarget: boolean = false
): 'who' | 'that' {
    return customAggregationTarget || aggregationGroupTypeIndex != null ? 'that' : 'who'
}
