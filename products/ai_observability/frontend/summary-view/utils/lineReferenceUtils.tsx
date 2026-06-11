/**
 * Utilities for parsing and handling line references in summaries
 */

/**
 * Parse line references like L45 in text and make them clickable
 * Schema enforces single line references only
 */
export function parseLineReferences(text: string): (string | JSX.Element)[] {
    const parts: (string | JSX.Element)[] = []
    // Match simple line references: L45 or [L45]
    const regex = /L\d+/g
    let lastIndex = 0
    let match

    while ((match = regex.exec(text)) !== null) {
        // Add text before the match
        if (match.index > lastIndex) {
            parts.push(text.slice(lastIndex, match.index))
        }

        // Extract line number
        const lineNumber = parseInt(match[0].slice(1)) // Remove 'L' and parse
        const displayText = `[${match[0]}]` // Always show with brackets for consistency

        parts.push(
            <button
                key={match.index}
                type="button"
                className="text-link hover:underline font-semibold cursor-pointer"
                data-attr="summary-line-reference-link"
                onClick={(e) => {
                    e.preventDefault()

                    // Scroll to the line
                    const element = document.getElementById(`summary-line-${lineNumber}`)
                    if (element) {
                        element.scrollIntoView({ behavior: 'smooth', block: 'center' })

                        // Highlight the line
                        element.classList.add('bg-warning-highlight')
                        element.classList.add('border-l-4')
                        element.classList.add('border-warning')
                    }

                    // Remove highlight after 3 seconds
                    setTimeout(() => {
                        const element = document.getElementById(`summary-line-${lineNumber}`)
                        if (element) {
                            element.classList.remove('bg-warning-highlight')
                            element.classList.remove('border-l-4')
                            element.classList.remove('border-warning')
                        }
                    }, 3000)
                }}
            >
                {displayText}
            </button>
        )

        lastIndex = regex.lastIndex
    }

    // Add remaining text
    if (lastIndex < text.length) {
        parts.push(text.slice(lastIndex))
    }

    return parts
}
