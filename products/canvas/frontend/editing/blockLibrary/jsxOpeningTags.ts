interface JsxAttribute {
    name: string | null
    start: number
    end: number
}

interface OpeningTag {
    attributes: JsxAttribute[]
    insertAt: number
}

function skipQuoted(source: string, from: number, quote: string): number {
    let index = from + 1
    while (index < source.length && source[index] !== quote) {
        if (source[index] === '\\') {
            index += 1
        }
        index += 1
    }
    return index + 1
}

function skipBraces(source: string, from: number): number {
    let depth = 0
    let index = from
    while (index < source.length) {
        const char = source[index]
        if (char === '"' || char === "'" || char === '`') {
            index = skipQuoted(source, index, char)
            continue
        }
        if (char === '{') {
            depth += 1
        }
        if (char === '}') {
            depth -= 1
            if (depth === 0) {
                return index + 1
            }
        }
        index += 1
    }
    return index
}

export function scanOpeningTag(source: string, start: number): OpeningTag | null {
    const head = /^<[A-Za-z][\w.]*/.exec(source.slice(start))
    if (!head) {
        return null
    }
    const attributes: JsxAttribute[] = []
    let index = start + head[0].length
    while (index < source.length) {
        while (/\s/.test(source[index] ?? '')) {
            index += 1
        }
        const char = source[index]
        if (char === '>') {
            return { attributes, insertAt: index }
        }
        if (char === '/' && source[index + 1] === '>') {
            return { attributes, insertAt: index }
        }
        if (char === '{') {
            const end = skipBraces(source, index)
            attributes.push({ name: null, start: index, end })
            index = end
            continue
        }
        const name = /^[A-Za-z_$][\w:.-]*/.exec(source.slice(index))
        if (!name) {
            return null
        }
        const attributeStart = index
        index += name[0].length
        if (source[index] === '=') {
            index += 1
            const value = source[index]
            if (value === '"' || value === "'") {
                index = skipQuoted(source, index, value)
            } else if (value === '{') {
                index = skipBraces(source, index)
            } else {
                return null
            }
        }
        attributes.push({ name: name[0], start: attributeStart, end: index })
    }
    return null
}

export function jsxOpeningTags(source: string, component: string): { start: number; end: number; tag: OpeningTag }[] {
    return Array.from(source.matchAll(/<([A-Za-z][\w.]*)\b/g)).flatMap((match) => {
        if (match[1] !== component) {
            return []
        }
        const tag = scanOpeningTag(source, match.index)
        return tag ? [{ start: match.index, end: tag.insertAt + (source[tag.insertAt] === '/' ? 2 : 1), tag }] : []
    })
}

export function jsxStringAttribute(source: string, tag: OpeningTag, name: string): string | null {
    const attribute = tag.attributes.find((attribute) => attribute.name === name)
    if (!attribute) {
        return null
    }
    let value = source.slice(attribute.start, attribute.end).slice(name.length).trim().replace(/^=\s*/, '')
    if (value.startsWith('{') && value.endsWith('}')) {
        value = value.slice(1, -1).trim()
    }
    if (value.startsWith('"')) {
        try {
            return JSON.parse(value) as string
        } catch {
            return null
        }
    }
    return value.startsWith("'") && value.endsWith("'") ? value.slice(1, -1) : null
}
