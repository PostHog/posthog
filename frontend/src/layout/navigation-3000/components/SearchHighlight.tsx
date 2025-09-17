import clsx from 'clsx'

interface Props {
    string: string
    substring: string
    className?: string
}

/**
 * Highlight a substring within a string (case-insensitive)
 * @param string - the aggregate string to search within (e.g. "Hello, world!")
 * @param substring - the substring to search for (e.g. "world")
 * @param className - additional classes to apply to the component
 */
export function SearchHighlight({ string, substring, className }: Props): JSX.Element {
    const parts = string.split(new RegExp(`(${substring})`, 'gi'))
    return (
        <div className={clsx('truncate flex-1', className)}>
            {parts.map((part, index) => (
                <span
                    key={index}
                    className={`text-xs ${
                        part.toLowerCase() === substring.toLowerCase() ? 'bg-accent bg-opacity-60' : ''
                    }`}
                >
                    {part}
                </span>
            ))}
        </div>
    )
}

/**
 * Highlight one or more space-delimited search terms within a string (case-insensitive).
 */
export function SearchHighlightMultiple({ string, substring, className }: Props): JSX.Element {
    // Split the substring by whitespace and slashes to get all search terms
    const searchTerms = substring.split(/[\s/]+/).filter(Boolean)

    // If there's nothing to search for, just render the string as-is.
    if (!searchTerms.length) {
        return <>{string}</>
    }

    // Lowercase version of the original string for case-insensitive matching
    const lowerString = string.toLowerCase()

    // Collect all match ranges [start, end]
    const allMatches: Array<[number, number]> = []

    // Find all occurrences (start/end indices) of each term in the main string
    searchTerms.forEach((term) => {
        const lowerTerm = term.toLowerCase()
        let startIndex = 0
        while (true) {
            const foundIndex = lowerString.indexOf(lowerTerm, startIndex)
            if (foundIndex === -1) {
                break
            }

            allMatches.push([foundIndex, foundIndex + term.length])
            startIndex = foundIndex + term.length
        }
    })

    // Sort matches by start index
    allMatches.sort((a, b) => a[0] - b[0])

    // Merge overlapping or contiguous ranges
    const mergedMatches: Array<[number, number]> = []
    for (let i = 0; i < allMatches.length; i++) {
        const [currentStart, currentEnd] = allMatches[i]
        if (!mergedMatches.length) {
            // If it's the first range, just push
            mergedMatches.push([currentStart, currentEnd])
        } else {
            const lastIndex = mergedMatches.length - 1
            const prevEnd = mergedMatches[lastIndex][1]
            if (currentStart <= prevEnd) {
                // Overlap or adjacency: extend the previous range end if necessary
                mergedMatches[lastIndex][1] = Math.max(prevEnd, currentEnd)
            } else {
                // No overlap: add the new range
                mergedMatches.push([currentStart, currentEnd])
            }
        }
    }

    // Build array of text parts (highlighted vs. non-highlighted)
    const highlightedParts: { text: string; highlight: boolean }[] = []
    let lastIndex = 0

    for (const [start, end] of mergedMatches) {
        // Add text before this highlight
        if (lastIndex < start) {
            highlightedParts.push({
                text: string.slice(lastIndex, start),
                highlight: false,
            })
        }
        // Add the highlighted text
        highlightedParts.push({
            text: string.slice(start, end),
            highlight: true,
        })
        lastIndex = end
    }

    // Add any remaining text after the last match
    if (lastIndex < string.length) {
        highlightedParts.push({
            text: string.slice(lastIndex),
            highlight: false,
        })
    }

    return (
        <span className={`truncate ${className ? className : ''}`}>
            {highlightedParts.map((part, index) => (
                <span key={index} className={part.highlight ? 'bg-accent-highlight-primary' : ''}>
                    {part.text}
                </span>
            ))}
        </span>
    )
}
