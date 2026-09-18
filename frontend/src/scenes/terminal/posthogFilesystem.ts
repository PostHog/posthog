import apiMutator from 'lib/api-orval-mutator'

import {
    fileSystemCreate,
    fileSystemDestroy,
    fileSystemList,
    fileSystemRetrieve,
    getFileSystemMoveCreateUrl,
} from '~/generated/core/api'
import type { FileSystemApi } from '~/generated/core/api.schemas'
import { joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'

import { dashboardsRetrieve } from 'products/dashboards/frontend/generated/api'
import { featureFlagsRetrieve } from 'products/feature_flags/frontend/generated/api'
import { notebooksList, notebooksPartialUpdate, notebooksRetrieve } from 'products/notebooks/frontend/generated/api'
import type { NotebookMinimalApi } from 'products/notebooks/frontend/generated/api.schemas'
import { insightsRetrieve } from 'products/product_analytics/frontend/generated/api'

import {
    FilesystemError,
    MAX_TERMINAL_FILE_BYTES,
    TerminalFile,
    TerminalFilesystem,
    TerminalNode,
} from './terminalFilesystem'

const encoder = new TextEncoder()
const decoder = new TextDecoder('utf-8', { fatal: true })

export function terminalFilename(name: string): string {
    const safe = name.replace(/[%/\x00-\x1f\x7f]/g, (character) => encodeURIComponent(character))
    if (encoder.encode(safe).length > 180) {
        // Leave room for extensions and collision suffixes within Linux's 255-byte limit.
        let prefix = ''
        for (const character of safe) {
            if (encoder.encode(prefix + character).length > 160) {
                break
            }
            prefix += character
        }
        let hash = 0xcbf29ce484222325n
        for (const byte of encoder.encode(safe)) {
            hash = BigInt.asUintN(64, (hash ^ BigInt(byte)) * 0x100000001b3n)
        }
        return `${prefix}~${hash.toString(16)}`
    }
    return safe === '.' || safe === '..' ? safe.replace(/\./g, '%2E') : safe || 'Untitled'
}

function markdownNode(
    content: unknown
): { attrs: { markdown: string; [key: string]: unknown }; [key: string]: unknown } | null {
    if (!content || typeof content !== 'object' || !('content' in content) || !Array.isArray(content.content)) {
        return null
    }
    const nodes = content.content
    if (
        nodes.length !== 1 ||
        nodes[0]?.type !== 'ph-markdown-notebook' ||
        typeof nodes[0]?.attrs?.markdown !== 'string'
    ) {
        return null
    }
    return nodes[0]
}

function bytes(text: string): Uint8Array {
    const result = encoder.encode(text)
    if (result.length > MAX_TERMINAL_FILE_BYTES) {
        throw new Error('This file exceeds the terminal file size limit of 4 MiB.')
    }
    return result
}

function jsonFile(value: unknown): TerminalFile {
    return { bytes: bytes(`${JSON.stringify(value, null, 2)}\n`) }
}

export const TERMINAL_README = `PostHog terminal

This is a Linux virtual machine running in your browser.

/posthog/files       Your project tree. Markdown notebooks have a .md extension.
/posthog/api         Read-only JSON representations, grouped by object type and ID.
/posthog/tools       Command descriptions and argument schemas. Run ph tools to discover MCP tools.
/posthog/recovery    Edits that could not be saved. Copy them before leaving this page.
/root and /tmp       Local Linux files. These disappear when the terminal closes.

Try:
  mc
  ls --color=auto /posthog/files
  find /posthog/files -name '*.md'
  grep -r 'revenue' /posthog/files
  cat '/posthog/files/Unfiled/Notebooks/My notebook.md'
  vi '/posthog/files/Unfiled/Notebooks/My notebook.md'
  nano '/posthog/files/Unfiled/Notebooks/My notebook.md'
  tree -C -L 3 /posthog/files
  ncdu -r /posthog/files
  jq '.title' /posthog/api/notebook/<short-id>.json
  ph help
  ph tools notebook
  ph notebook-get '/posthog/files/Unfiled/Notebooks/My notebook.md'

Saving an existing .md notebook updates PostHog using your current permissions.
Writes commit on fsync or close. Concurrent edits fail instead of overwriting
someone else's changes. Check the browser's save error banner and /posthog/recovery.
Use mkdir to create project folders and mv to move or rename files and folders
inside /posthog/files. Keep .md or .json extensions when renaming files.
Moves preserve object IDs and folder contents. Existing destinations cannot be
replaced. Use rm to remove files, rmdir for empty folders, and rm -r for folder trees.
Removing the last file reference deletes the PostHog object, using your permissions.
Files open for writing must be closed before removal. Use ph notebook-create to create notebooks.
Work in /tmp for programs that save by renaming a temporary file,
then use cat /tmp/edited.md > '/posthog/files/path/to/notebook.md'.

Directories are a snapshot from startup. File contents load from the API on open.
Listing directories never downloads object contents. Sizes are zero until a file
is opened, then show its last known size. Startup uses the notebook index to find
markdown notebooks without fetching their bodies.
Run ph refresh to discover new or renamed objects. Unsupported object types
expose their filesystem record as JSON. Legacy rich-text notebooks stay JSON.
Characters that cannot appear in Unix filenames are percent-encoded. Duplicate
names receive an ID suffix. Long names get a shortened prefix and stable hash.
Extensions do not change the names stored in PostHog.

The VM has no network connection and receives no API tokens or session cookies.
The browser makes authenticated requests through the existing PostHog APIs.
Files are limited to 4 MiB. Use Ctrl+C to interrupt, Tab to complete, and the
mouse wheel for scrollback. Run busybox to see the installed Unix utilities.
jq 1.8.2 is installed for JSON queries and formatting.
nano 8.4 edits text with syntax highlighting. Ctrl+S saves; Ctrl+X exits.
mc opens Midnight Commander. Tab switches panels; F3 views, F4 edits, F10 quits.
Use Escape then a digit if your browser or keyboard captures function keys.
mcview, mcedit, and mcdiff also run directly from the shell.
tree lists folders and files. ncdu -r browses disk usage without allowing deletion.
Project file sizes stay zero until opened; ncdu does not download their contents.
Bundled tool licenses and source links are in /opt/posthog-tools/licenses.
ph runs project commands and tools from connected MCP servers with your permissions.
Run ph help <command> for its arguments. Notebook commands accept IDs or file paths.
Use --json @file.json or --json - for arguments from a file or stdin.
Commands such as ph notebook-delete change real data. Errors exit nonzero.
Selecting text copies it automatically. You can also copy with Cmd+C (macOS) or
Ctrl+Shift+C (Linux/Windows).
Paste with Cmd+V or Ctrl+Shift+V, or use the Copy selection and Paste buttons.

Browser agents can use window.posthogTerminal.write('ls\\n') and
window.posthogTerminal.read() to interact with this same terminal.
`

export class PosthogFilesystem extends TerminalFilesystem {
    private readonly files = this.directory('files', this.root)
    private readonly api = this.directory('api', this.root)
    private readonly references = new Map<string, FileSystemApi>()
    private readonly projectNodes = new Map<
        TerminalNode,
        { parts: string[]; entry?: FileSystemApi; extension?: string }
    >()

    resolveReference(value: string, cwd: string, type?: string): string {
        const parts: string[] = []
        for (const part of (value.startsWith('/') ? value : `${cwd}/${value}`).split('/')) {
            if (part === '..') {
                parts.pop()
            } else if (part && part !== '.') {
                parts.push(part)
            }
        }
        const entry = this.references.get(`/${parts.join('/')}`)
        if (entry) {
            if (type && entry.type !== type) {
                throw new Error(`Expected a ${type} file, but this is a ${entry.type} file.`)
            }
            if (!entry.ref) {
                throw new Error('This file has no object ID. Pass the tool an ID directly.')
            }
            return entry.ref
        }
        if (value.includes('/') || /\.(md|json)$/.test(value)) {
            throw new Error(`No project file at ${value}. Run ph refresh if the file was just created.`)
        }
        return value
    }

    constructor(
        private projectId: string,
        private signal: AbortSignal
    ) {
        super()
        this.text('README.txt', this.root, TERMINAL_README)
        this.registerDirectory(this.files, [])
    }

    private registerDirectory(node: TerminalNode, parts: string[], entry?: FileSystemApi): void {
        this.projectNodes.set(node, { parts, entry })
        node.mkdir = async (name) => {
            const directory = this.projectNodes.get(node)
            if (!directory) {
                throw new FilesystemError(116)
            }
            const parts = [...directory.parts, this.storedName(name)]
            const entry = await fileSystemCreate(
                this.projectId,
                { path: joinPath(parts), type: 'folder' },
                { signal: this.signal }
            )
            const child = this.directory(name, node)
            this.registerDirectory(child, parts, entry)
            return child
        }
        if (node !== this.files) {
            node.rename = (parent, name) => this.move(node, parent, name)
            node.remove = () => this.remove(node)
        }
    }

    private storedName(name: string): string {
        try {
            const decoded = decodeURIComponent(name)
            return terminalFilename(decoded) === name ? decoded : name
        } catch {
            return name
        }
    }

    private mountedPath(node: TerminalNode): string {
        const parts = [node.name]
        for (let parent = node.parent; parent && parent !== this.root; parent = parent.parent) {
            parts.unshift(parent.name)
        }
        return `/posthog/${parts.join('/')}`
    }

    private async remove(node: TerminalNode): Promise<void> {
        const source = this.projectNodes.get(node)
        if (!source || node.removed) {
            throw new FilesystemError(116)
        }
        if (node.children?.size) {
            throw new FilesystemError(39)
        }
        if (source.entry) {
            try {
                await fileSystemDestroy(this.projectId, source.entry.id, { recursive: false }, { signal: this.signal })
            } catch (error) {
                const status = error && typeof error === 'object' && 'status' in error ? error.status : undefined
                throw new FilesystemError(status === 409 ? 39 : status === 403 ? 13 : status === 404 ? 2 : 5)
            }
        }
        this.references.delete(this.mountedPath(node))
        this.projectNodes.delete(node)
        node.parent!.children!.delete(node.name)
        node.removed = true
        const entry = source.entry
        if (
            entry &&
            !node.children &&
            ![...this.projectNodes.values()].some(
                ({ entry: other }) => other && other.type === entry.type && other.ref === entry.ref
            )
        ) {
            const type = this.api.children!.get(terminalFilename(entry.type ?? 'unknown'))
            const name = `${terminalFilename(entry.ref ?? entry.id)}.json`
            const apiNode = type?.children?.get(name)
            if (apiNode) {
                apiNode.removed = true
                this.references.delete(this.mountedPath(apiNode))
                type!.children!.delete(name)
            }
        }
    }

    private async move(node: TerminalNode, parent: TerminalNode, name: string): Promise<void> {
        const source = this.projectNodes.get(node)
        const destination = this.projectNodes.get(parent)
        if (!source || !destination) {
            throw new FilesystemError(116)
        }
        if (source.extension && !name.endsWith(source.extension)) {
            throw new FilesystemError(22)
        }
        const originalName = source.parts[source.parts.length - 1]
        const projectedExtension = source.extension && !originalName.endsWith(source.extension) ? source.extension : ''
        const basename =
            name === node.name
                ? originalName
                : this.storedName(projectedExtension ? name.slice(0, -projectedExtension.length) : name)
        if (!basename) {
            throw new FilesystemError(22)
        }
        const parts = [...destination.parts, basename]
        const entry =
            source.entry ??
            (await fileSystemCreate(
                this.projectId,
                { path: joinPath(source.parts), type: 'folder' },
                { signal: this.signal }
            ))
        source.entry = entry
        // The generated move body describes a filesystem row, but this action requires new_path.
        await apiMutator<FileSystemApi>(getFileSystemMoveCreateUrl(this.projectId, entry.id), {
            method: 'POST',
            body: JSON.stringify({ new_path: joinPath(parts) }),
            signal: this.signal,
        })
        const descendants = [...this.projectNodes].filter(([candidate]) => {
            for (let ancestor: TerminalNode | undefined = candidate; ancestor; ancestor = ancestor.parent) {
                if (ancestor === node) {
                    return true
                }
            }
            return false
        })
        for (const [child] of descendants) {
            this.references.delete(this.mountedPath(child))
        }
        const oldDepth = source.parts.length
        node.parent!.children!.delete(node.name)
        node.parent = parent
        node.name = name
        parent.children!.set(name, node)
        for (const [child, metadata] of descendants) {
            metadata.parts = [...parts, ...metadata.parts.slice(oldDepth)]
            if (metadata.entry) {
                metadata.entry.path = joinPath(metadata.parts)
                this.references.set(this.mountedPath(child), metadata.entry)
            }
        }
    }

    private async object(entry: FileSystemApi): Promise<unknown> {
        const options = { signal: this.signal }
        const ref = entry.ref ?? ''
        switch (entry.type) {
            case 'notebook':
                return notebooksRetrieve(this.projectId, ref, options)
            case 'dashboard':
                return dashboardsRetrieve(this.projectId, Number(ref), undefined, options)
            case 'insight':
                return insightsRetrieve(this.projectId, ref, undefined, options)
            case 'feature_flag':
                return featureFlagsRetrieve(this.projectId, Number(ref), options)
            default:
                return fileSystemRetrieve(this.projectId, entry.id, options)
        }
    }

    private async notebook(entry: FileSystemApi): Promise<TerminalFile> {
        let notebook = await notebooksRetrieve(this.projectId, entry.ref!, { signal: this.signal })
        const node = markdownNode(notebook.content)
        if (!node) {
            throw new Error('Notebook format changed. Restart the terminal to refresh the filename.')
        }
        return {
            bytes: bytes(node.attrs.markdown),
            save: async (data) => {
                const markdown = decoder.decode(data)
                notebook = await notebooksPartialUpdate(
                    this.projectId,
                    entry.ref!,
                    {
                        content: {
                            ...(notebook.content as object),
                            content: [{ ...node, attrs: { ...node.attrs, markdown } }],
                        },
                        text_content: markdown,
                        version: notebook.version,
                    },
                    { signal: this.signal }
                )
            },
        }
    }

    async load(): Promise<void> {
        const entries: FileSystemApi[] = []
        let offset = 0
        while (true) {
            const page = await fileSystemList(this.projectId, { limit: 500, offset }, { signal: this.signal })
            entries.push(...page.results)
            if (!page.next) {
                break
            }
            if (!page.results.length || entries.length > 50_000) {
                throw new Error('This project tree is too large for the terminal experiment.')
            }
            offset += page.results.length
        }
        entries.sort((a, b) => a.path.localeCompare(b.path) || a.id.localeCompare(b.id))
        const markdownNotebooks = new Map<string, NotebookMinimalApi>()
        if (entries.some((entry) => entry.type === 'notebook')) {
            let offset = 0
            while (true) {
                const page = await notebooksList(
                    this.projectId,
                    { contains: 'markdown-notebook', limit: 500, offset },
                    { signal: this.signal }
                )
                for (const notebook of page.results) {
                    markdownNotebooks.set(notebook.short_id, notebook)
                }
                if (!page.next) {
                    break
                }
                if (!page.results.length || offset > 50_000) {
                    throw new Error('This notebook index is too large for the terminal experiment.')
                }
                offset += page.results.length
            }
        }
        this.files.children!.clear()
        this.api.children!.clear()
        this.references.clear()
        this.projectNodes.clear()
        this.registerDirectory(this.files, [])
        for (const entry of entries.filter((item) => item.type === 'folder' && item.user_access_level !== 'none')) {
            const parts = splitPath(entry.path)
            this.registerDirectory(this.parent(parts, this.files), parts, entry)
        }
        for (const entry of entries) {
            if (entry.type === 'folder' || entry.user_access_level === 'none') {
                continue
            }
            const notebook = entry.type === 'notebook' ? markdownNotebooks.get(entry.ref ?? '') : undefined
            const parts = splitPath(entry.path)
            const basename = terminalFilename(parts.pop() ?? 'Untitled')
            const parent = this.parent(parts, this.files)
            const extension = notebook ? '.md' : '.json'
            let name = basename.endsWith(extension) ? basename : `${basename}${extension}`
            if (parent.children!.has(name)) {
                name = `${basename}~${entry.id}${extension}`
            }
            let duplicate = 1
            while (parent.children!.has(name)) {
                name = `${basename}~${entry.id}-${duplicate++}${extension}`
            }
            const file = this.file(
                name,
                parent,
                notebook ? () => this.notebook(entry) : async () => jsonFile(await this.object(entry)),
                !!notebook &&
                    (notebook.user_access_level === null ||
                        ['editor', 'manager'].includes(notebook.user_access_level ?? ''))
            )
            this.projectNodes.set(file, { parts: splitPath(entry.path), entry, extension })
            file.rename = (parent, name) => this.move(file, parent, name)
            file.remove = () => this.remove(file)
            this.references.set(`/posthog/files/${[...parts.map(terminalFilename), name].join('/')}`, entry)
            const type = this.directory(terminalFilename(entry.type ?? 'unknown'), this.api)
            const apiName = `${terminalFilename(entry.ref ?? entry.id)}.json`
            if (!type.children!.has(apiName)) {
                this.file(apiName, type, async () => jsonFile(await this.object(entry)))
                this.references.set(`/posthog/api/${type.name}/${apiName}`, entry)
            }
        }
    }

    private parent(parts: string[], root: TerminalNode): TerminalNode {
        return parts.reduce((parent, part, index) => {
            const node = this.directory(terminalFilename(part), parent)
            if (!this.projectNodes.has(node)) {
                this.registerDirectory(node, parts.slice(0, index + 1))
            }
            return node
        }, root)
    }
}
