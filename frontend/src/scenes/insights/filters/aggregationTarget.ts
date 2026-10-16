export const UNIQUE_USERS = 'person_id'

export function getHogQLValue(groupIndex?: number | null, aggregationQuery?: string | null): string {
    if (groupIndex != undefined) {
        return `$group_${groupIndex}`
    } else if (aggregationQuery) {
        return aggregationQuery
    }
    return UNIQUE_USERS
}

export function hogQLToFilterValue(value?: string): { groupIndex?: number; aggregationQuery?: string } {
    if (value?.match(/^\$group_[0-9]+$/)) {
        return { groupIndex: parseInt(value.replace('$group_', '')) }
    } else if (value === 'person_id') {
        return {}
    }
    return { aggregationQuery: value }
}
