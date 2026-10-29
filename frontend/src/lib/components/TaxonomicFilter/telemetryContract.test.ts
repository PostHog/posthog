import fs from 'fs'
import path from 'path'

const COMPONENTS_DIR = path.resolve(__dirname, '..')
const SOURCE_ROOTS = [
    path.join(COMPONENTS_DIR, 'TaxonomicFilter'),
    path.join(COMPONENTS_DIR, 'TaxonomicPopover'),
    path.join(COMPONENTS_DIR, 'PropertyFilters/components/taxonomicPropertyFilterLogic.ts'),
    path.resolve(COMPONENTS_DIR, '../utils/eventUsageLogic.ts'),
]
const CONTRACT_PATH = path.resolve(
    __dirname,
    '../../../../../.agents/skills/modifying-taxonomic-filter/references/telemetry-contract.md'
)
// Each section of the contract states whether its events carry `surface`, so it is not listed per event.
const IMPLIED_PROPERTIES = new Set(['surface'])

function sourceFiles(root: string): string[] {
    if (fs.statSync(root).isFile()) {
        return [root]
    }
    return fs.readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
        const full = path.join(root, entry.name)
        if (entry.isDirectory()) {
            return sourceFiles(full)
        }
        return /\.tsx?$/.test(entry.name) && !/\.(test|stories)\.tsx?$/.test(entry.name) ? [full] : []
    })
}

function matchingBrace(text: string, open: number): number {
    let depth = 0
    for (let i = open; i < text.length; i++) {
        if (text[i] === '{') {
            depth++
        } else if (text[i] === '}' && --depth === 0) {
            return i
        }
    }
    return -1
}

function objectKeys(body: string): string[] {
    const withoutComments = body.replace(/\/\/[^\n]*/g, '')
    const entries: string[] = []
    let depth = 0
    let current = ''
    for (const char of withoutComments) {
        if ('{[('.includes(char)) {
            depth++
        } else if ('}])'.includes(char)) {
            depth--
        }
        if (char === ',' && depth === 0) {
            entries.push(current)
            current = ''
        } else {
            current += char
        }
    }
    entries.push(current)
    return entries.flatMap((raw) => {
        const entry = raw.trim()
        if (entry.startsWith('...')) {
            const open = entry.indexOf('{')
            return open === -1 ? [] : objectKeys(entry.slice(open + 1, matchingBrace(entry, open)))
        }
        const key = entry.match(/^['"]?([\w$]+)['"]?\s*(?::|$)/)
        return key ? [key[1]] : []
    })
}

function capturedEvents(): Map<string, Set<string>> {
    const events = new Map<string, Set<string>>()
    for (const file of SOURCE_ROOTS.flatMap(sourceFiles)) {
        const text = fs.readFileSync(file, 'utf8')
        for (const match of text.matchAll(/posthog\.capture\(\s*['"](taxonomic[^'"]+)['"]\s*(,\s*\{)?/g)) {
            const keys = events.get(match[1]) ?? new Set<string>()
            if (match[2]) {
                const open = match.index + match[0].length - 1
                objectKeys(text.slice(open + 1, matchingBrace(text, open))).forEach((key) => keys.add(key))
            }
            events.set(match[1], keys)
        }
    }
    return events
}

function documentedEvents(): Map<string, string> {
    const documented = new Map<string, string>()
    let current: string | null = null
    for (const line of fs.readFileSync(CONTRACT_PATH, 'utf8').split('\n')) {
        const bullet = line.match(/^- `(taxonomic[^`]+)`/)
        if (bullet) {
            current = bullet[1]
            documented.set(current, (documented.get(current) ?? '') + line)
        } else if (current && line.startsWith('  ')) {
            documented.set(current, documented.get(current) + line)
        } else {
            current = null
        }
    }
    return documented
}

const captured = capturedEvents()
const documented = documentedEvents()

describe('taxonomic filter telemetry contract', () => {
    test.each([...captured.entries()].map(([event, keys]) => [event, [...keys]]))(
        '%s is listed in telemetry-contract.md with every property it sends',
        (event, keys) => {
            const entry = documented.get(event as string)
            expect(entry).not.toBeUndefined()
            const missing = (keys as string[]).filter(
                (key) => !IMPLIED_PROPERTIES.has(key) && !entry?.includes(`\`${key}\``)
            )
            expect(missing).toEqual([])
        }
    )

    it('lists no event that the frontend no longer sends', () => {
        const stale = [...documented.keys()].filter((event) => !captured.has(event))
        expect(stale).toEqual([])
    })
})
