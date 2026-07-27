import React from 'react'

import { findSearchMatches } from './searchUtils'

interface SearchHighlightProps {
    string: string
    substring: string
    className?: string
}

/**
 * Highlights all search occurrences in the string.
 */
export const SearchHighlight = React.forwardRef<HTMLSpanElement, SearchHighlightProps>(
    ({ string, substring, className }, ref) => {
        // If no search, return plain text
        if (!substring.trim()) {
            return (
                <span ref={ref} className={className}>
                    {string}
                </span>
            )
        }

        // Find all occurrences in this string
        const matches = findSearchMatches(string, substring)

        // If no occurrences found, return plain text
        if (matches.length === 0) {
            return (
                <span ref={ref} className={className}>
                    {string}
                </span>
            )
        }

        // Build parts array with text segments and highlights
        const parts: JSX.Element[] = []
        let lastIndex = 0

        matches.forEach((match, i) => {
            // Add text before this highlight
            if (lastIndex < match.startIndex) {
                parts.push(<span key={`text-${i}`}>{string.slice(lastIndex, match.startIndex)}</span>)
            }

            // Add the highlighted text with bg-danger styling
            parts.push(
                <span key={`highlight-${i}`} className="bg-danger text-white">
                    {string.slice(match.startIndex, match.startIndex + match.length)}
                </span>
            )

            lastIndex = match.startIndex + match.length
        })

        // Add remaining text
        if (lastIndex < string.length) {
            parts.push(<span key="text-final">{string.slice(lastIndex)}</span>)
        }

        return (
            <span ref={ref} className={className}>
                {parts}
            </span>
        )
    }
)

SearchHighlight.displayName = 'SearchHighlight'
