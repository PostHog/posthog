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
export default function SearchHighlight({ string, substring, className }: Props): JSX.Element {
    const parts = string.split(new RegExp(`(${substring})`, 'gi'))
    return (
        <div className={`truncate ${className}`}>
            {parts.map((part, index) => (
                <span
                    key={index}
                    className={`text-xs ${
                        part.toLowerCase() === substring.toLowerCase() ? 'bg-accent-primary bg-opacity-60' : ''
                    }`}
                >
                    {part}
                </span>
            ))}
        </div>
    )
}
