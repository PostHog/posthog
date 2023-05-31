import { SearchMatch } from '../types'

/**
 * Return a search match with instances of the search term highlighted in the string.
 * This provides highlighting for server-side search, which does not return data on how the search term was matched.
 */
export function findSearchTermInItemName(name: string, searchTerm: string): SearchMatch | null {
    if (!searchTerm || !name) {
        return null
    }
    const ranges: [number, number][] = []
    const workingName = name.toLowerCase()
    const workingSearchTerm = searchTerm.toLowerCase()
    let index = workingName.indexOf(workingSearchTerm)
    while (index !== -1) {
        console.log(index)
        ranges.push([index, index + searchTerm.length])
        index = workingName.indexOf(workingSearchTerm, index + 1)
    }
    return ranges.length ? { nameHighlightRanges: ranges } : null
}
