import type { KnowledgeSourceApi, SourceTypeEnumApi } from '../generated/api.schemas'

export type SourceTypeFilter = SourceTypeEnumApi[]

export interface KnowledgeSourceListFilters {
    searchTerm: string
    sourceTypeFilter: SourceTypeFilter
    learnedOnly: boolean
}

export const SOURCE_TYPE_FILTER_OPTIONS: readonly { key: SourceTypeEnumApi; label: string }[] = [
    { key: 'text', label: 'Text' },
    { key: 'url', label: 'URL' },
    { key: 'file', label: 'File' },
]

function sourceSearchHaystack(source: KnowledgeSourceApi): string {
    const parts = [source.name, source.source_url, source.original_filename]
    if (source.learned_from_ticket_number != null) {
        parts.push(`ticket #${source.learned_from_ticket_number}`)
    }
    return parts.join(' ').toLowerCase()
}

export function filterKnowledgeSources(
    sources: KnowledgeSourceApi[],
    { searchTerm, sourceTypeFilter, learnedOnly }: KnowledgeSourceListFilters
): KnowledgeSourceApi[] {
    const needle = searchTerm.trim().toLowerCase()
    return sources.filter((source) => {
        if (sourceTypeFilter.length > 0 && !sourceTypeFilter.includes(source.source_type)) {
            return false
        }
        if (learnedOnly && !source.is_generated) {
            return false
        }
        if (needle && !sourceSearchHaystack(source).includes(needle)) {
            return false
        }
        return true
    })
}
