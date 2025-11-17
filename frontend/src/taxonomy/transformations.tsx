import { Link } from 'lib/lemon-ui/Link'

import { CoreFilterDefinition } from '~/types'

type RawCoreFilterDefinition = {
    label: string
    description?: string
    examples?: (string | number | boolean)[]
    system?: boolean
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
