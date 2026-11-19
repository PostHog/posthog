import { pluralTypeName } from './commandKFilterOptions'
import { FilterKey, QueryChip, ResolvedQuery } from './commandKQuery'

const FILTER_PHRASES: Record<Exclude<FilterKey, 'is'>, (chip: QueryChip) => string> = {
    createdBy: ({ value, label, negated }) =>
        `${negated ? 'not created' : 'created'} by ${value === 'me' ? 'me' : label}`,
    in: ({ label, negated }) => `${negated ? 'outside' : 'in'} ${label}`,
    name: ({ label, negated }) => `with a name ${negated ? 'not containing' : 'containing'} "${label}"`,
}

function objectNoun(type: QueryChip | undefined): string {
    if (!type) {
        return 'objects'
    }
    if (type.negated) {
        return `objects that are not ${pluralTypeName(type.label)}`
    }
    return pluralTypeName(type.label)
}

// Filters with no free text ask nothing: the filters alone already answer the search.
export function askAiQuestionFor(text: string, { filters, freeText }: ResolvedQuery): string | null {
    if (filters.length === 0) {
        return text.trim() || null
    }
    const search = freeText.trim()
    if (!search) {
        return null
    }
    const phrases = filters.flatMap((chip) => (chip.key === 'is' ? [] : [FILTER_PHRASES[chip.key](chip)]))
    return ['Find', objectNoun(filters.find((chip) => chip.key === 'is')), ...phrases, `called "${search}"`].join(' ')
}
