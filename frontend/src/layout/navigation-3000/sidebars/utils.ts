import { SearchMatch } from '../types'

export function findSearchTermInItemName(name: string, searchTerm: string): SearchMatch | null {
    if (!searchTerm) {
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
