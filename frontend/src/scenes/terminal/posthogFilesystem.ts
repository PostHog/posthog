import { fileSystemList, fileSystemRetrieve } from '~/generated/core/api'
import type { FileSystemApi } from '~/generated/core/api.schemas'
import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'

import { dashboardsRetrieve } from 'products/dashboards/frontend/generated/api'
import { featureFlagsRetrieve } from 'products/feature_flags/frontend/generated/api'
import { notebooksList, notebooksPartialUpdate, notebooksRetrieve } from 'products/notebooks/frontend/generated/api'
import type { NotebookMinimalApi } from 'products/notebooks/frontend/generated/api.schemas'
import { insightsRetrieve } from 'products/product_analytics/frontend/generated/api'

import { MAX_TERMINAL_FILE_BYTES, TerminalFile, TerminalFilesystem, TerminalNode } from './terminalFilesystem'

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
  ls --color=auto /posthog/files
  find /posthog/files -name '*.md'
  grep -r 'revenue' /posthog/files
  cat '/posthog/files/Unfiled/Notebooks/My notebook.md'
  vi '/posthog/files/Unfiled/Notebooks/My notebook.md'
  jq '.title' /posthog/api/notebook/<short-id>.json
  ph help
  ph tools notebook
  ph notebook-get '/posthog/files/Unfiled/Notebooks/My notebook.md'

Saving an existing .md notebook updates PostHog using your current permissions.
Writes commit on fsync or close. Concurrent edits fail instead of overwriting
someone else's changes. Check the browser's save error banner and /posthog/recovery.
Use in-place writes; creating, deleting, moving and replacing project files are
not supported. Work in /tmp for programs that save by renaming a temporary file,
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
ph runs project commands and tools from connected MCP servers with your permissions.
Run ph help <command> for its arguments. Notebook commands accept IDs or file paths.
Use --json @file.json or --json - for arguments from a file or stdin.
Commands such as ph notebook-delete change real data. Errors exit nonzero.
Select text to copy with Cmd+C (macOS) or Ctrl+Shift+C (Linux/Windows).
Paste with Cmd+V or Ctrl+Shift+V, or use the Copy selection and Paste buttons.

Browser agents can use window.posthogTerminal.write('ls\\n') and
window.posthogTerminal.read() to interact with this same terminal.
`

export class PosthogFilesystem extends TerminalFilesystem {
    private readonly files = this.directory('files', this.root)
    private readonly api = this.directory('api', this.root)
    private readonly references = new Map<string, FileSystemApi>()

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
        for (const entry of entries.filter((item) => item.type === 'folder')) {
            this.parent(splitPath(entry.path), this.files)
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
            this.file(
                name,
                parent,
                notebook ? () => this.notebook(entry) : async () => jsonFile(await this.object(entry)),
                !!notebook &&
                    (notebook.user_access_level === null ||
                        ['editor', 'manager'].includes(notebook.user_access_level ?? ''))
            )
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
        return parts.reduce((parent, part) => this.directory(terminalFilename(part), parent), root)
    }
}
