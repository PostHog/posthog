import { dateFromToText } from 'lib/utils/dateFilters'

import { CompareFilter } from '~/queries/schema/schema-general'

export function compareFilterLabel(compareFilter: CompareFilter | null | undefined): string {
    if (!compareFilter?.compare) {
        return 'No comparison'
    }
    if (compareFilter.compare_to) {
        return `${dateFromToText(compareFilter.compare_to) ?? compareFilter.compare_to} earlier`
    }
    return 'Previous period'
}
