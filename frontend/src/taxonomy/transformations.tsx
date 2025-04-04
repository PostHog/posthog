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
}

function transformDescription(description: string): React.ReactNode {
    if (!description.includes('\n') && !description.includes('`')) {
        return description
    }

    const parts = description.split(/(`[^`]+`|\n)/)
    return (
        <>
            {parts.map((part, i) => {
                if (part === '\n') {
                    return <br key={i} />
                }
                if (part.startsWith('`') && part.endsWith('`')) {
                    return <code key={i}>{part.slice(1, -1)}</code>
                }
                return part
            })}
        </>
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
