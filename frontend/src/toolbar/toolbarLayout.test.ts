import fs from 'fs'
import path from 'path'

type Zone = 'shared' | 'floating' | 'extension'

const TOOLBAR_DIR = __dirname
const SRC_DIR = path.resolve(TOOLBAR_DIR, '..')
const ALLOWED_IMPORTS: Record<Zone, Zone[]> = {
    shared: ['shared'],
    floating: ['shared', 'floating'],
    extension: ['shared', 'extension'],
}
const SPECIFIER = /(?:\bfrom\s+|\bimport\s*\(\s*|\bimport\s+|\brequire\s*\(\s*|\bjest\.\w+\s*\(\s*)['"]([^'"\n]+)['"]/g

function zoneOf(file: string): Zone | null {
    const [zone] = path.relative(TOOLBAR_DIR, file).split(path.sep)
    return zone === 'shared' || zone === 'floating' || zone === 'extension' ? zone : null
}

function sourceFiles(dir: string): string[] {
    return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const fullPath = path.join(dir, entry.name)
        if (entry.isDirectory()) {
            return sourceFiles(fullPath)
        }
        return /\.(ts|tsx)$/.test(entry.name) ? [fullPath] : []
    })
}

function importedPath(specifier: string, fromFile: string): string | null {
    if (specifier.startsWith('.')) {
        return path.resolve(path.dirname(fromFile), specifier)
    }
    if (specifier.startsWith('~/')) {
        return path.join(SRC_DIR, specifier.slice(2))
    }
    return null
}

describe('toolbar layout', () => {
    it('keeps shared code free of floating and extension code, and the two forms apart', () => {
        const violations: string[] = []
        for (const file of sourceFiles(TOOLBAR_DIR)) {
            const zone = zoneOf(file)
            if (!zone) {
                continue
            }
            for (const [, specifier] of fs.readFileSync(file, 'utf8').matchAll(SPECIFIER)) {
                const target = importedPath(specifier, file)
                const targetZone = target ? zoneOf(target) : null
                if (targetZone && !ALLOWED_IMPORTS[zone].includes(targetZone)) {
                    violations.push(`${path.relative(TOOLBAR_DIR, file)} imports ${specifier}`)
                }
            }
        }
        expect(violations).toEqual([])
    })
})
