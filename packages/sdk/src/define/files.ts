import { callerFile } from './definition.js'

interface FileSystem {
    readFileSync(path: string, encoding: 'utf8'): string
    readdirSync(
        path: string,
        options: { withFileTypes: true }
    ): { name: string; isDirectory(): boolean; isFile(): boolean }[]
}

interface PathModule {
    resolve(...parts: string[]): string
    dirname(path: string): string
    join(...parts: string[]): string
}

// Loaded on call, not imported, so an app that imports these definitions' types into a browser
// bundle never pulls in `node:fs`.
function builtins(): { fs: FileSystem; path: PathModule } {
    const load = (globalThis as { process?: { getBuiltinModule?: (name: string) => unknown } }).process
        ?.getBuiltinModule
    if (typeof load !== 'function') {
        throw new Error('file() and contextPages() read files, so they run only under Node or Bun.')
    }
    return { fs: load('node:fs') as FileSystem, path: load('node:path') as PathModule }
}

export function resolveFromCaller(relativePath: string): string {
    const { path } = builtins()
    const from = callerFile()
    return from ? path.resolve(path.dirname(from), relativePath) : path.resolve(relativePath)
}

// The text of a file, relative to the file that calls it. Long SQL and Markdown stay as files.
export function file(relativePath: string): string {
    return builtins().fs.readFileSync(resolveFromCaller(relativePath), 'utf8')
}

// Every `.md` file under a folder, relative to the calling file, as paths relative to that folder
// with forward slashes, sorted, with their text.
export function markdownFiles(relativeFolder: string): { path: string; content: string }[] {
    const { fs, path } = builtins()
    const root = resolveFromCaller(relativeFolder)
    const found: { path: string; content: string }[] = []
    const walk = (folder: string, prefix: string): void => {
        const entries = fs.readdirSync(folder, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : 1))
        for (const entry of entries) {
            const relative = prefix ? `${prefix}/${entry.name}` : entry.name
            if (entry.isDirectory()) {
                walk(path.join(folder, entry.name), relative)
            } else if (entry.isFile() && entry.name.endsWith('.md')) {
                found.push({ path: relative, content: fs.readFileSync(path.join(folder, entry.name), 'utf8') })
            }
        }
    }
    walk(root, '')
    return found
}
