/**
 * Displays line-numbered text representation
 */
export interface TextReprDisplayProps {
    textRepr: string
}

export function TextReprDisplay({ textRepr }: TextReprDisplayProps): JSX.Element {
    const lines = textRepr.split('\n')

    return (
        <div className="p-4 overflow-auto h-full font-mono text-xs whitespace-pre bg-bg-light">
            {lines.map((line, index) => {
                // Extract line number from zero-padded format "L001:", "L010:", "L100:"
                const match = line.match(/^(L\d+:)(.*)$/)
                // Parse to int to remove leading zeros so ID matches what click handlers expect
                const lineNumber = match ? parseInt(match[1].slice(1, -1), 10) : null
                const linePrefix = match ? match[1] : ''
                const lineContent = match ? match[2] : line

                return (
                    <div
                        key={index}
                        id={lineNumber ? `summary-line-${lineNumber}` : undefined}
                        className="transition-all duration-300 ease-in-out"
                    >
                        {linePrefix && <span className="text-muted">{linePrefix}</span>}
                        {lineContent}
                    </div>
                )
            })}
        </div>
    )
}
