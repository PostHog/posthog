import type { SearchItem } from 'lib/components/Search/searchItems'

import { searchWords } from './commandKRanking'

const MAX_SHAPE_LENGTH = 100
const vocabularies = new WeakMap<SearchItem[], Set<string>>()

function vocabularyOf(items: SearchItem[]): Set<string> {
    let vocabulary = vocabularies.get(items)
    if (!vocabulary) {
        vocabulary = new Set(
            items.flatMap((item) => [
                ...searchWords(String(item.displayName || item.name)),
                ...(item.searchKeywords ?? []).flatMap(searchWords),
            ])
        )
        vocabularies.set(items, vocabulary)
    }
    return vocabulary
}

/** Keeps the words of a search that PostHog's own product and settings names use, and masks every other word. */
export function queryShape(query: string, publicLists: SearchItem[][]): string {
    const vocabularies = publicLists.map(vocabularyOf)
    return searchWords(query)
        .map((word) => (vocabularies.some((vocabulary) => vocabulary.has(word)) ? word : '*'))
        .join(' ')
        .slice(0, MAX_SHAPE_LENGTH)
}
