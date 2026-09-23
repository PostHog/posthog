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

import { actionsPartialUpdate, actionsRetrieve } from 'products/actions/frontend/generated/api'
import { cohortsPartialUpdate, cohortsRetrieve } from 'products/cohorts/frontend/generated/api'
import { dashboardsPartialUpdate, dashboardsRetrieve } from 'products/dashboards/frontend/generated/api'
import { experimentsPartialUpdate, experimentsRetrieve } from 'products/experiments/frontend/generated/api'
import { featureFlagsPartialUpdate, featureFlagsRetrieve } from 'products/feature_flags/frontend/generated/api'
import { notebooksList, notebooksPartialUpdate, notebooksRetrieve } from 'products/notebooks/frontend/generated/api'
import type { NotebookMinimalApi } from 'products/notebooks/frontend/generated/api.schemas'
import { insightsPartialUpdate, insightsRetrieve } from 'products/product_analytics/frontend/generated/api'
import { surveysPartialUpdate, surveysRetrieve } from 'products/surveys/frontend/generated/api'

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
    // xterm runs C0, DEL and C1 code points as control functions, so a printed name must not contain them.
    const safe = name.replace(/[%/\x00-\x1f\x7f-\x9f]/g, (character) => encodeURIComponent(character))
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

export function markdownNode(
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
/posthog/api         JSON representations, grouped by object type and ID.
/posthog/tools       Command descriptions and argument schemas. Run ph tools to discover MCP tools.
/posthog/recovery    Edits that could not be saved. Copy them before leaving this page.
/root and /tmp       Local Linux files. These disappear when you stop Linux or reload PostHog.

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
JSON files for notebooks, dashboards, insights, feature flags, cohorts, actions,
surveys, and experiments are editable in both mounts when you have edit access.
Saving sends changed JSON fields to the existing API endpoint with PATCH. The mounted
path selects the object, even if you edit an ID inside the JSON. API validation
and read-only fields still apply. Unsupported object types remain read-only.
Writes commit on fsync or close. Notebook saves use version checks; other objects
use their API's update behavior. Invalid JSON and API failures fail the save.
Check the browser's save error banner and /posthog/recovery for failed edits.
Use mkdir to create project folders and mv to move or rename files and folders
inside /posthog/files. Keep .md or .json extensions when renaming files.
Moves preserve object IDs and folder contents. Existing destinations cannot be
replaced. Folders inferred from file paths cannot be moved; move their files instead.
Use rm to remove files, rmdir for empty folders, and rm -r for folder trees.
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
        const entry = source.entry
        if (!entry) {
            // Creating an implicit folder before moving it cannot be rolled back safely when it has children.
            throw new FilesystemError(95)
        }
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

    private validReference(entry: FileSystemApi): boolean {
        const ref = entry.ref
        if (!ref) {
            return false
        }
        switch (entry.type) {
            case 'notebook':
                return /^[\p{L}\p{N}]{1,12}(?![\s\S])/u.test(ref)
            case 'insight':
                return /^(?:[A-Za-z0-9]{1,12}|[0-9]+)(?![\s\S])/.test(ref)
            case 'survey':
                return /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?![\s\S])/i.test(ref)
            case 'dashboard':
            case 'feature_flag':
            case 'cohort':
            case 'action':
            case 'experiment':
                return /^[1-9][0-9]*(?![\s\S])/.test(ref) && Number.isSafeInteger(Number(ref))
            default:
                return false
        }
    }

    private objectApi(
        entry: FileSystemApi,
        signal?: AbortSignal
    ):
        | {
              read: () => Promise<unknown>
              update: (data: Record<string, unknown>) => Promise<unknown>
          }
        | undefined {
        const options = { signal: this.signal }
        const readOptions = { signal: signal ?? this.signal }
        const ref = entry.ref
        if (!ref || !this.validReference(entry)) {
            return undefined
        }
        switch (entry.type) {
            case 'notebook':
                return {
                    read: () => notebooksRetrieve(this.projectId, ref, readOptions),
                    update: (data) => notebooksPartialUpdate(this.projectId, ref, data, options),
                }
            case 'dashboard':
                return {
                    read: () => dashboardsRetrieve(this.projectId, Number(ref), undefined, readOptions),
                    update: (data) => dashboardsPartialUpdate(this.projectId, Number(ref), data, undefined, options),
                }
            case 'insight':
                return {
                    read: () => insightsRetrieve(this.projectId, ref, undefined, readOptions),
                    update: (data) => insightsPartialUpdate(this.projectId, ref, data, undefined, options),
                }
            case 'feature_flag':
                return {
                    read: () => featureFlagsRetrieve(this.projectId, Number(ref), readOptions),
                    update: (data) => featureFlagsPartialUpdate(this.projectId, Number(ref), data, options),
                }
            case 'cohort':
                return {
                    read: () => cohortsRetrieve(this.projectId, Number(ref), readOptions),
                    update: (data) => cohortsPartialUpdate(this.projectId, Number(ref), data, options),
                }
            case 'action':
                return {
                    read: () => actionsRetrieve(this.projectId, Number(ref), undefined, readOptions),
                    update: (data) => actionsPartialUpdate(this.projectId, Number(ref), data, undefined, options),
                }
            case 'survey':
                return {
                    read: () => surveysRetrieve(this.projectId, ref, readOptions),
                    update: (data) => surveysPartialUpdate(this.projectId, ref, data, options),
                }
            case 'experiment':
                return {
                    read: () => experimentsRetrieve(this.projectId, Number(ref), readOptions),
                    update: (data) => experimentsPartialUpdate(this.projectId, Number(ref), data, options),
                }
            default:
                return undefined
        }
    }

    private async json(entry: FileSystemApi, writable: boolean, signal?: AbortSignal): Promise<TerminalFile> {
        const endpoint = this.objectApi(entry, signal)
        let value = endpoint
            ? await endpoint.read()
            : await fileSystemRetrieve(this.projectId, entry.id, {
                  signal: signal ?? this.signal,
              })
        return {
            ...jsonFile(value),
            save:
                writable && endpoint
                    ? async (data) => {
                          let update: unknown
                          try {
                              update = JSON.parse(decoder.decode(data))
                          } catch {
                              throw new Error('Invalid JSON. Fix the JSON syntax before saving.')
                          }
                          if (!update || typeof update !== 'object' || Array.isArray(update)) {
                              throw new Error('The JSON must contain an object with the fields to update.')
                          }
                          const original = value && typeof value === 'object' ? value : {}
                          const payload = Object.fromEntries(
                              Object.entries(update).filter(
                                  ([key, value]) =>
                                      JSON.stringify(value) !==
                                      JSON.stringify((original as Record<string, unknown>)[key])
                              )
                          )
                          if (!Object.keys(payload).length) {
                              return
                          }
                          if (entry.type === 'notebook' && 'content' in payload && !('text_content' in payload)) {
                              const node = markdownNode(payload.content)
                              if (!node) {
                                  throw new Error('Include text_content when changing non-markdown notebook content.')
                              }
                              payload.text_content = node.attrs.markdown
                          }
                          // These APIs skip their conflict check when `version` is absent, and the
                          // filter above drops it because it matches what the read returned. A cohort
                          // stays out: its version counts calculations rather than writes.
                          if (
                              ['notebook', 'experiment', 'feature_flag'].includes(entry.type ?? '') &&
                              value &&
                              typeof value === 'object' &&
                              'version' in value
                          ) {
                              payload.version = value.version
                          }
                          value = await endpoint.update(payload)
                      }
                    : undefined,
        }
    }

    private async notebook(entry: FileSystemApi, signal?: AbortSignal): Promise<TerminalFile> {
        if (!this.validReference(entry)) {
            throw new FilesystemError(22)
        }
        let notebook = await notebooksRetrieve(this.projectId, entry.ref!, {
            signal: signal ?? this.signal,
        })
        const node = markdownNode(notebook.content)
        if (!node) {
            throw new Error('Notebook format changed. Restart the terminal to refresh the filename.')
        }
        let saved = node.attrs.markdown
        return {
            bytes: bytes(saved),
            save: async (data) => {
                const markdown = decoder.decode(data)
                // Editors rewrite the whole file on save, so a save that changed nothing would
                // otherwise bump the version and reattribute the last edit to the person who
                // only looked at the notebook.
                if (markdown === saved) {
                    return
                }
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
                saved = markdown
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
        const previousNodes = this.mountedNodes()
        const directories = new Map(
            [...previousNodes].filter((node) => node.children).map((node) => [this.mountedPath(node), node])
        )
        const files = new Map(
            [...this.projectNodes]
                .filter(([, metadata]) => metadata.entry && metadata.extension)
                .map(([node, metadata]) => [this.fileIdentity(metadata.entry!, metadata.extension!), node])
        )
        const apiFiles = new Map(
            [...previousNodes]
                .filter((node) => !node.children && node.parent?.parent === this.api)
                .map((node) => [this.mountedPath(node), node])
        )
        for (const node of previousNodes) {
            node.children?.clear()
        }
        this.references.clear()
        this.projectNodes.clear()
        this.registerDirectory(this.files, [])
        for (const entry of entries.filter((item) => item.type === 'folder' && item.user_access_level !== 'none')) {
            const parts = splitPath(entry.path)
            this.registerDirectory(this.parent(parts, this.files, directories), parts, entry)
        }
        for (const entry of entries) {
            if (entry.type === 'folder' || entry.user_access_level === 'none') {
                continue
            }
            const notebook = entry.type === 'notebook' ? markdownNotebooks.get(entry.ref ?? '') : undefined
            const parts = splitPath(entry.path)
            const basename = terminalFilename(parts.pop() ?? 'Untitled')
            const parent = this.parent(parts, this.files, directories)
            const extension = notebook ? '.md' : '.json'
            let name = basename.endsWith(extension) ? basename : `${basename}${extension}`
            if (parent.children!.has(name)) {
                name = `${basename}~${entry.id}${extension}`
            }
            let duplicate = 1
            while (parent.children!.has(name)) {
                name = `${basename}~${entry.id}-${duplicate++}${extension}`
            }
            const access = notebook?.user_access_level ?? entry.user_access_level
            const writable =
                !!this.objectApi(entry) &&
                entry.user_access_level !== 'viewer' &&
                (access === null || ['editor', 'manager'].includes(access ?? ''))
            const file = this.mountFile(
                name,
                parent,
                notebook ? (signal) => this.notebook(entry, signal) : (signal) => this.json(entry, writable, signal),
                writable,
                files.get(this.fileIdentity(entry, extension))
            )
            file.writeKey = JSON.stringify([entry.type, entry.ref ?? entry.id])
            this.projectNodes.set(file, { parts: splitPath(entry.path), entry, extension })
            file.rename = (parent, name) => this.move(file, parent, name)
            file.remove = () => this.remove(file)
            this.references.set(`/posthog/files/${[...parts.map(terminalFilename), name].join('/')}`, entry)
            const type = this.mountDirectory(terminalFilename(entry.type ?? 'unknown'), this.api, directories)
            const apiName = `${terminalFilename(entry.ref ?? entry.id)}.json`
            if (!type.children!.has(apiName)) {
                const apiFile = this.mountFile(
                    apiName,
                    type,
                    (signal) => this.json(entry, writable, signal),
                    writable,
                    apiFiles.get(`${this.mountedPath(type)}/${apiName}`)
                )
                apiFile.writeKey = file.writeKey
                this.references.set(`/posthog/api/${type.name}/${apiName}`, entry)
            }
        }
        const currentNodes = this.mountedNodes()
        for (const node of previousNodes) {
            if (!currentNodes.has(node)) {
                node.removed = true
            }
        }
    }

    private fileIdentity(entry: FileSystemApi, extension: string): string {
        return JSON.stringify([entry.id, entry.type, entry.ref, extension])
    }

    private mountedNodes(): Set<TerminalNode> {
        const nodes = new Set<TerminalNode>([this.files, this.api])
        for (const node of nodes) {
            for (const child of node.children?.values() ?? []) {
                nodes.add(child)
            }
        }
        return nodes
    }

    private mountDirectory(name: string, parent: TerminalNode, directories: Map<string, TerminalNode>): TerminalNode {
        const node = directories.get(`${this.mountedPath(parent)}/${name}`) ?? this.directory(name, parent)
        parent.children!.set(name, node)
        return node
    }

    private async readFile(
        open: (signal?: AbortSignal) => Promise<TerminalFile>,
        signal?: AbortSignal
    ): Promise<TerminalFile> {
        if (!signal) {
            return open(this.signal)
        }
        const controller = new AbortController()
        const abort = (): void => controller.abort()
        this.signal.addEventListener('abort', abort, { once: true })
        signal.addEventListener('abort', abort, { once: true })
        try {
            if (this.signal.aborted || signal.aborted) {
                controller.abort()
            }
            return await open(controller.signal)
        } finally {
            this.signal.removeEventListener('abort', abort)
            signal.removeEventListener('abort', abort)
        }
    }

    private mountFile(
        name: string,
        parent: TerminalNode,
        open: (signal?: AbortSignal) => Promise<TerminalFile>,
        writable: boolean,
        existing?: TerminalNode
    ): TerminalNode {
        const node = existing ?? this.file(name, parent, open, writable)
        node.name = name
        node.parent = parent
        node.writable = writable
        node.open = async (signal) => {
            if (node.removed) {
                throw new FilesystemError(116)
            }
            const file = await this.readFile(open, signal)
            const save = file.save
            return {
                ...file,
                save: save
                    ? async (bytes) => {
                          if (node.removed) {
                              throw new FilesystemError(116)
                          }
                          await save(bytes)
                      }
                    : undefined,
            }
        }
        parent.children!.set(name, node)
        return node
    }

    private parent(parts: string[], root: TerminalNode, directories: Map<string, TerminalNode>): TerminalNode {
        return parts.reduce((parent, part, index) => {
            const node = this.mountDirectory(terminalFilename(part), parent, directories)
            if (!this.projectNodes.has(node)) {
                this.registerDirectory(node, parts.slice(0, index + 1))
            }
            return node
        }, root)
    }
}
