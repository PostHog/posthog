import { AnyPropertyFilter, PropertyFilterType } from '~/types'

export const SCREEN_NAME_PROPERTY = '$screen_name'

export function isScreenNameFilter(p: AnyPropertyFilter): boolean {
    return 'key' in p && p.key === SCREEN_NAME_PROPERTY && p.type === PropertyFilterType.Event
}

export type ScreenNameMatching = 'exact' | 'icontains' | 'regex'

export const SCREEN_NAME_MATCHING_LABEL: Record<ScreenNameMatching, string> = {
    exact: 'matches exactly',
    regex: 'matches regex',
    icontains: 'contains',
}
