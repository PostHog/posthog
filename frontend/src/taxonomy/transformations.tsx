import { Link } from 'lib/lemon-ui/Link'

type RawCoreFilterDefinition = {
    label: string
    description?: string
    examples?: (string | number)[]
    system?: boolean
}

type CoreFilterDefinition = {
    label: string
    description?: string | React.ReactNode
    examples?: (string | number)[]
    system?: boolean
    /** whether this is a property PostHog adds to aid with debugging */
    used_for_debug?: boolean
}

function transformDescription(description: string): React.ReactNode {
    if (!description.includes('\n') && !description.includes('`') && !description.includes('[')) {
        return description
    }

    const parts = description.split(/(\[.*?\]\(.*?\)|`[^`]+`|\n)/)
    return (
        <span>
            {parts.map((part, i) => {
                if (part === '\n') {
                    return <br key={i} />
                }
                if (part.startsWith('`') && part.endsWith('`')) {
                    return <code key={i}>{part.slice(1, -1)}</code>
                }
                const linkMatch = part.match(/\[(.*?)\]\((.*?)\)/)
                if (linkMatch) {
                    const [_, text, url] = linkMatch
                    return (
                        <Link key={i} to={url}>
                            {text}
                        </Link>
                    )
                }
                return part
            })}
        </span>
    )
}

export function transformFilterDefinitions(
    group: Record<string, RawCoreFilterDefinition>
): Record<string, CoreFilterDefinition> {
    const result: Record<string, CoreFilterDefinition> = {}
    for (const [key, def] of Object.entries(group)) {
        result[key] = {
            ...def,
            description: def.description ? transformDescription(def.description) : undefined,
        }
    }
    return result
}
