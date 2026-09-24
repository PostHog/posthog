import apiMutator from 'lib/api-orval-mutator'
import { urls } from 'scenes/urls'

import {
    fileSystemCreate,
    fileSystemDestroy,
    fileSystemList,
    fileSystemRetrieve,
    getFileSystemMoveCreateUrl,
} from '~/generated/core/api'
import type { FileSystemApi, FileSystemListParams } from '~/generated/core/api.schemas'
import { joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { fileSystemTypes } from '~/products'
import type { HogQLQuery } from '~/queries/schema/schema-general'
import type { ProjectTreeRef } from '~/types'

import { actionsPartialUpdate, actionsRetrieve } from 'products/actions/frontend/generated/api'
import { cohortsPartialUpdate, cohortsRetrieve } from 'products/cohorts/frontend/generated/api'
import { dashboardsPartialUpdate, dashboardsRetrieve } from 'products/dashboards/frontend/generated/api'
import { experimentsPartialUpdate, experimentsRetrieve } from 'products/experiments/frontend/generated/api'
import { featureFlagsPartialUpdate, featureFlagsRetrieve } from 'products/feature_flags/frontend/generated/api'
import { notebooksPartialUpdate, notebooksRetrieve } from 'products/notebooks/frontend/generated/api'
import { insightsPartialUpdate, insightsRetrieve } from 'products/product_analytics/frontend/generated/api'
import { surveysPartialUpdate, surveysRetrieve } from 'products/surveys/frontend/generated/api'

import { ConfirmTerminalOperation, TerminalConfirmation } from './terminalConfirmation'
import {
    FilesystemError,
    MAX_TERMINAL_FILE_BYTES,
    TerminalFile,
    TerminalFilesystem,
    TerminalNode,
} from './terminalFilesystem'
import { hasTerminalSql, parseTerminalSql, terminalQuery, terminalSql } from './terminalSql'

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

/posthog/files       Your project tree. Markdown notebooks use .md; SQL insights use .sql.
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
  open .
  open '/posthog/files/Unfiled/Notebooks/My notebook.md'

open [path] opens a project file or folder in PostHog. With no path, it opens the
current folder. JSON files open their PostHog item, including files in /posthog/api.
Folders open in the Files tab when the simple side panel is enabled.

Optional tools download on first use: node, pi, nyancat, and doom.
In Doom, W/S move, A/D strafe, left/right arrows turn, Space fires, E opens doors,
and Shift runs. Use Capture mouse to turn with the mouse; left-click fires.

Saving a .sql insight updates its query and preserves its query options.
Use run report.sql to execute SQL, or run --help for JSON, CSV, and TSV exports.
The terminal follows the current resource's folder while its prompt is empty. Active commands and typed input stay intact.

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
inside /posthog/files. Keep .md, .sql, or .json extensions when renaming files.
Moves preserve object IDs and folder contents. Existing destinations cannot be
replaced. Folders inferred from file paths cannot be moved; move their files instead.
Use rm to remove files, rmdir for empty folders, and rm -r for folder trees.
Project writes and connected tools require a blocking confirmation. Click a button
to approve or cancel; keyboard input cannot approve changes. rm groups its PostHog targets into
one confirmation. Other programs confirm each removal. Local Linux files do not
require confirmation. Delete local and PostHog files in separate commands.
Removing the last file reference deletes the PostHog object, using your permissions.
Files open for writing must be closed before removal. Use ph notebook-create to create notebooks.
Work in /tmp for programs that save by renaming a temporary file,
then use cat /tmp/edited.md > '/posthog/files/path/to/notebook.md'.

Directories load when you browse them and stay cached until ph refresh.
The terminal starts without downloading the project tree. Browsing /posthog/files
loads one folder at a time; /posthog/api loads one object type at a time.
Listing directories never downloads object contents. File contents load on open.
Sizes are zero until a file is opened, then show its last known size.
Filenames use content types from the filesystem listing. Notebook and insight
contents load only when you open a file.
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
node (or nodejs) installs Node.js on first use. pi installs the pi coding harness
and Node.js on first use. Try node --version or pi --help.
For a break, try these commands. Each downloads on first use:
  sl                 Run a steam train across the terminal
  cmatrix            Watch Matrix-style falling text (q quits)
  figlet PostHog     Print an ASCII banner; also accepts piped text
  nyancat            Watch an animated rainbow cat (Ctrl+C quits)
Ctrl+C also stops the train and Matrix animation.
The browser downloads verified packages from GitHub and caches them when storage
is available. Stopping the terminal discards the installed files and local sessions.
pi uses PostHog AI through your signed-in session and defaults to Claude Opus 5.
Use /model in pi to choose Opus 5, Sonnet 5, Sonnet 4.6, or Haiku 4.5.
Try pi -p 'What can ph tools do?'
Run one pi session at a time. AI credit limits apply. Gateway setup is required.
The VM has no general network access, so external login and package downloads are unavailable.
Use /tmp for local scripts and pi sessions; mounted PostHog files keep their API rules.
Project file sizes stay zero until opened; ncdu does not download their contents.
Bundled tool licenses and source links are in /opt/posthog-tools/licenses.
ph runs project commands and tools from connected MCP servers with your permissions.
Run ph help <command> for its arguments. Notebook commands accept IDs or file paths.
The interactive Bash shell completes ph commands and their --arguments with Tab.
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
    private readonly mountedFiles = new Map<string, TerminalNode>()
    private readonly projectNodes = new Map<
        TerminalNode,
        { parts: string[]; entry?: FileSystemApi; extension?: string }
    >()

    private readonly loadedDirectories = new Set<TerminalNode>()
    private readonly pendingDirectories = new Map<TerminalNode, Promise<void>>()
    private directoryQueue: Promise<void> = Promise.resolve()

    async folderFor(ref: ProjectTreeRef | null): Promise<string | null> {
        if (!ref) {
            return null
        }
        if (ref.type === 'folder') {
            return this.folderPath(ref.ref ?? '')
        }
        if (!ref.ref) {
            return null
        }
        // The filesystem endpoint accepts type/ref filters that its generated schema omits.
        const params = { type: ref.type, ref: ref.ref, limit: 1 }
        const page = await fileSystemList(this.projectId, params, { signal: this.signal })
        const entry = page.results.find(
            (entry) => entry.type === ref.type && entry.ref === ref.ref && entry.user_access_level !== 'none'
        )
        return entry ? this.folderPath(joinPath(splitPath(entry.path).slice(0, -1))) : null
    }

    folderPath(path: string): string {
        return ['/posthog/files', ...splitPath(path).map(terminalFilename)].join('/')
    }

    async queryFor(path: string, text: string): Promise<HogQLQuery> {
        await this.loadReference(path, '/posthog/files')
        const entry = this.references.get(path)
        const original =
            entry?.type === 'insight'
                ? await insightsRetrieve(this.projectId, entry.ref!, undefined, { signal: this.signal })
                : undefined
        return terminalQuery(text, original as Record<string, unknown> | undefined)
    }

    async navigationUrl(value: string, cwd: string): Promise<string> {
        const parts = (value.startsWith('/') ? value : `${cwd}/${value}`).split('/').filter(Boolean)
        if (parts.shift() !== 'posthog') {
            throw new Error('Open a project file or folder under /posthog/files or /posthog/api.')
        }
        let node: TerminalNode | undefined = this.root
        for (const part of parts) {
            if (!node) {
                break
            }
            if (part === '..') {
                node = node.parent
            } else if (part !== '.') {
                await node.loadChildren?.()
                node = node.children?.get(part) ?? node.lookupChild?.(part)
            }
        }
        if (!node || node.removed) {
            throw new Error(`No project file or folder at ${value}. Run ph refresh if it was just created.`)
        }
        const projectNode = this.projectNodes.get(node)
        if (node.children && projectNode) {
            return urls.projectFiles(joinPath(projectNode.parts))
        }
        const entry = this.references.get(this.mountedPath(node))
        const type = entry?.type
        const definition =
            type && Object.hasOwn(fileSystemTypes, type)
                ? fileSystemTypes[type as keyof typeof fileSystemTypes]
                : undefined
        const href = entry?.href || (entry?.ref && definition?.href(entry.ref))
        if (!href || !href.startsWith('/') || href.startsWith('//') || /[\\\x00-\x20]/.test(href)) {
            throw new Error('This path has no PostHog page. Use cat to read the file in the terminal.')
        }
        return href
    }

    async loadReference(value: string, cwd: string): Promise<void> {
        if (!value.includes('/') && !/\.(md|json|sql)$/.test(value)) {
            return
        }
        const parts = (value.startsWith('/') ? value : `${cwd}/${value}`).split('/').filter(Boolean)
        if (parts.shift() !== 'posthog') {
            return
        }
        let node: TerminalNode | undefined = this.root
        for (const part of parts) {
            if (!node) {
                return
            }
            if (part === '..') {
                node = node.parent ?? node
            } else if (part !== '.') {
                await node.loadChildren?.()
                node = node.children?.get(part) ?? node.lookupChild?.(part)
            }
        }
    }

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
        if (value.includes('/') || /\.(md|json|sql)$/.test(value)) {
            throw new Error(`No project file at ${value}. Run ph refresh if the file was just created.`)
        }
        return value
    }

    constructor(
        private projectId: string,
        private signal: AbortSignal,
        private confirm: ConfirmTerminalOperation = async () => false,
        private confirmWrites = false
    ) {
        super()
        this.text('README.txt', this.root, TERMINAL_README)
        this.registerDirectory(this.files, [])
        this.mountApiDirectories(new Map())
        this.api.lookupChild = (name) => {
            const node = this.directory(name, this.api)
            node.loadChildren = () => this.ensureDirectory(node)
            return node
        }
    }

    private registerDirectory(node: TerminalNode, parts: string[], entry?: FileSystemApi): void {
        this.projectNodes.set(node, { parts, entry })
        node.loadChildren = () => this.ensureDirectory(node)
        node.mkdir = async (name) => {
            const directory = this.projectNodes.get(node)
            if (!directory) {
                throw new FilesystemError(116)
            }
            const parts = [...directory.parts, this.storedName(name)]
            await this.confirmWrite({
                title: 'Create a PostHog folder?',
                description: `Create a folder in project ${this.projectId}. This affects everyone in the project.`,
                items: [joinPath(parts)],
            })
            const entry = await fileSystemCreate(
                this.projectId,
                { path: joinPath(parts), type: 'folder' },
                { signal: this.signal }
            )
            const child = this.directory(name, node)
            this.registerDirectory(child, parts, entry)
            this.loadedDirectories.add(child)
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

    async confirmOperation(confirmation: TerminalConfirmation): Promise<void> {
        if (this.signal.aborted || !(await this.confirm(confirmation)) || this.signal.aborted) {
            throw new Error('Canceled. No changes made.')
        }
    }

    async confirmWrite(confirmation: TerminalConfirmation): Promise<void> {
        if (this.confirmWrites) {
            await this.confirmOperation(confirmation)
        }
    }

    private removalConfirmation(nodes: TerminalNode[]): TerminalConfirmation {
        return {
            title: 'Delete PostHog files and folders?',
            description: `Remove ${nodes.length === 1 ? '1 file or folder' : `${nodes.length} files and folders`} from project ${this.projectId}. Removing the last file reference also deletes the PostHog object. This affects everyone in the project.`,
            items: nodes.map((node) => {
                const entry = this.projectNodes.get(node)?.entry
                return `${this.mountedPath(node)}${entry && entry.type !== 'folder' ? ` (${entry.type}: ${entry.ref})` : ''}`
            }),
        }
    }

    async removePaths(paths: string[], recursive: boolean, force: boolean): Promise<void> {
        const nodes = new Set<TerminalNode>()
        const visit = async (node: TerminalNode): Promise<void> => {
            if (nodes.has(node)) {
                return
            }
            if (!node.remove || this.writers.has(node.writeKey ?? node.id)) {
                throw new FilesystemError(
                    node.remove ? 16 : 30,
                    `Could not delete ${this.mountedPath(node)}: ${node.remove ? 'Device or resource busy. Close the file before deleting it.' : 'Read-only file system. Choose a writable path.'}`
                )
            }
            if (node.children) {
                if (!recursive) {
                    throw new FilesystemError(
                        21,
                        `Could not delete ${this.mountedPath(node)}: Is a directory. Use rm -r to delete folders.`
                    )
                }
                await node.loadChildren?.()
                for (const child of node.children.values()) {
                    await visit(child)
                }
            }
            nodes.add(node)
        }
        for (const path of paths) {
            if (!path.startsWith('/posthog/files/')) {
                throw new Error(
                    'Delete local files and PostHog files in separate commands. Use a path inside /posthog/files.'
                )
            }
            let node: TerminalNode | undefined = this.files
            for (const part of path.slice('/posthog/files/'.length).split('/')) {
                if (!part || part === '.' || part === '..') {
                    throw new Error('Use a resolved path inside /posthog/files.')
                }
                await node?.loadChildren?.()
                node = node?.children?.get(part)
            }
            if (node) {
                await visit(node)
            } else if (!force) {
                throw new FilesystemError(2, `Could not delete ${path}: No such file or directory. Check the path.`)
            }
        }
        if (!nodes.size) {
            return
        }
        await this.confirmOperation(this.removalConfirmation([...nodes]))
        for (const node of nodes) {
            await this.remove(node, true)
        }
    }

    private async remove(node: TerminalNode, confirmed = false): Promise<void> {
        const source = this.projectNodes.get(node)
        if (!source || node.removed) {
            throw new FilesystemError(116)
        }
        if (node.children?.size) {
            throw new FilesystemError(39)
        }
        if (this.writers.has(node.writeKey ?? node.id)) {
            throw new FilesystemError(16)
        }
        if (!confirmed) {
            await this.confirmOperation(this.removalConfirmation([node]))
        }
        if (this.signal.aborted) {
            throw new FilesystemError(4)
        }
        if (source.entry) {
            try {
                await fileSystemDestroy(this.projectId, source.entry.id, { recursive: false }, { signal: this.signal })
            } catch (error) {
                const status = error && typeof error === 'object' && 'status' in error ? error.status : undefined
                throw new FilesystemError(
                    status === 409 ? 39 : status === 403 ? 13 : status === 404 ? 2 : 5,
                    `Could not delete ${this.mountedPath(node)}${status ? ` (HTTP ${status})` : ''}:\n${error instanceof Error ? error.message : 'API request failed'}\nRun ph refresh to check the remaining files before trying again.`
                )
            }
        }
        this.references.delete(this.mountedPath(node))
        this.projectNodes.delete(node)
        if (source.entry && source.extension) {
            this.mountedFiles.delete(this.fileIdentity(source.entry, source.extension))
        }
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
        await this.confirmWrite({
            title: 'Move a PostHog file or folder?',
            description: `Move or rename an item in project ${this.projectId}. This affects everyone in the project.`,
            items: [`${this.mountedPath(node)} → /posthog/files/${joinPath(parts)}`],
        })
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

    private async document(
        entry: FileSystemApi,
        writable: boolean,
        signal?: AbortSignal,
        sql = false
    ): Promise<TerminalFile> {
        const endpoint = this.objectApi(entry, signal)
        let value = endpoint
            ? await endpoint.read()
            : await fileSystemRetrieve(this.projectId, entry.id, {
                  signal: signal ?? this.signal,
              })
        if (sql && !hasTerminalSql(value)) {
            throw new Error('This insight no longer contains SQL. Run ph refresh to reload its filename.')
        }
        return {
            ...(sql ? { bytes: bytes(terminalSql(value as Record<string, unknown>)) } : jsonFile(value)),
            save:
                writable && endpoint
                    ? async (data) => {
                          let update: unknown
                          try {
                              update = sql
                                  ? parseTerminalSql(decoder.decode(data), value as Record<string, unknown>)
                                  : JSON.parse(decoder.decode(data))
                          } catch {
                              throw new Error(
                                  sql
                                      ? 'Invalid SQL text. Save the file as UTF-8 before trying again.'
                                      : 'Invalid JSON. Fix the JSON syntax before saving.'
                              )
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
                          if (payload.deleted) {
                              await this.confirmOperation({
                                  title: 'Delete a PostHog object?',
                                  description: `Save a deletion to ${entry.type} ${entry.ref} in project ${this.projectId}. This affects everyone in the project.`,
                                  items: [JSON.stringify(payload, null, 2)],
                              })
                          } else {
                              await this.confirmWrite({
                                  title: 'Save changes to a PostHog object?',
                                  description: `Update ${entry.type} ${entry.ref} in project ${this.projectId}. This affects everyone in the project.`,
                                  items: [JSON.stringify(payload, null, 2)],
                              })
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
                await this.confirmWrite({
                    title: 'Save changes to a PostHog notebook?',
                    description: `Update notebook ${entry.ref} in project ${this.projectId}. This affects everyone in the project.`,
                    items: [markdown],
                })
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

    private mountApiDirectories(directories: Map<string, TerminalNode>): void {
        const names = new Set([
            ...Object.keys(fileSystemTypes).map(terminalFilename),
            'unknown',
            ...[...directories.values()].filter((node) => node.parent === this.api).map((node) => node.name),
        ])
        for (const name of names) {
            const node = this.mountDirectory(name, this.api, directories)
            node.loadChildren = () => this.ensureDirectory(node)
        }
    }

    private ensureDirectory(node: TerminalNode): Promise<void> {
        if (this.loadedDirectories.has(node)) {
            return Promise.resolve()
        }
        const pending = this.pendingDirectories.get(node)
        if (pending) {
            return pending
        }
        const request = this.directoryQueue.then(() => this.loadDirectory(node))
        this.pendingDirectories.set(node, request)
        this.directoryQueue = request.catch(() => {})
        void request.finally(() => this.pendingDirectories.delete(node)).catch(() => {})
        return request
    }

    private directoryParams(
        node: TerminalNode
    ): FileSystemListParams & { parent?: string; depth?: number; type?: string } {
        if (node.removed) {
            throw new FilesystemError(116)
        }
        const directory = this.projectNodes.get(node)
        const type = node.parent === this.api ? this.storedName(node.name) : undefined
        if (!directory && !type) {
            throw new FilesystemError(116)
        }
        // The list endpoint supports parent/depth/type filters that its generated schema omits.
        return directory ? { parent: joinPath(directory.parts), depth: directory.parts.length + 1 } : { type }
    }

    private async directoryEntries(params: ReturnType<PosthogFilesystem['directoryParams']>): Promise<FileSystemApi[]> {
        const entries: FileSystemApi[] = []
        let offset = 0
        while (true) {
            const page = await fileSystemList(
                this.projectId,
                { ...params, include_content_type: true, limit: 500, offset },
                { signal: this.signal }
            )
            entries.push(...page.results)
            if (!page.next) {
                return entries
            }
            if (!page.results.length || entries.length > 50_000) {
                throw new Error('This directory is too large for the terminal. Open a smaller folder instead.')
            }
            offset += page.results.length
        }
    }

    private async loadDirectory(node: TerminalNode): Promise<void> {
        const entries = await this.directoryEntries(this.directoryParams(node))
        this.mountEntries(entries, true)
        this.loadedDirectories.add(node)
    }

    private async refreshDirectories(): Promise<void> {
        const directories = this.loadedDirectories.size ? [...this.loadedDirectories] : [this.files]
        const scopes = directories.filter((node) => !node.removed).map((node) => this.directoryParams(node))
        const parents = new Set(scopes.flatMap((scope) => (scope.parent === undefined ? [] : [scope.parent])))
        const types = new Set(scopes.flatMap((scope) => (scope.type === undefined ? [] : [scope.type])))
        const inScope = (entry: FileSystemApi): boolean =>
            types.has(entry.type ?? 'unknown') || parents.has(joinPath(splitPath(entry.path).slice(0, -1)))
        const previousEntries = [...this.projectNodes.values()].flatMap(({ entry }) => (entry ? [entry] : []))
        const refreshed = new Map<string, FileSystemApi>()
        for (const scope of scopes) {
            for (const entry of await this.directoryEntries(scope)) {
                refreshed.set(entry.id, entry)
            }
        }
        const removedFolders = new Set(
            previousEntries
                .filter(
                    (entry) => entry.type === 'folder' && inScope(entry) && refreshed.get(entry.id)?.path !== entry.path
                )
                .map((entry) => entry.path)
        )
        const retained = previousEntries.filter((entry) => {
            if (inScope(entry)) {
                return false
            }
            const parts = splitPath(entry.path)
            for (let depth = 1; depth < parts.length; depth++) {
                if (removedFolders.has(joinPath(parts.slice(0, depth)))) {
                    return false
                }
            }
            return true
        })
        const merged = new Map(retained.map((entry) => [entry.id, entry]))
        for (const entry of refreshed.values()) {
            merged.set(entry.id, entry)
        }
        this.mountEntries([...merged.values()])
        for (const node of directories) {
            if (!node.removed) {
                this.loadedDirectories.add(node)
            }
        }
    }

    load(): Promise<void> {
        const request = this.directoryQueue.then(() => this.refreshDirectories())
        this.directoryQueue = request.catch(() => {})
        return request
    }

    private mountEntries(entries: FileSystemApi[], incremental = false): void {
        entries.sort((a, b) => a.path.localeCompare(b.path) || a.id.localeCompare(b.id))
        const previousNodes = incremental ? new Set<TerminalNode>() : this.mountedNodes()
        const directories = new Map(
            [...previousNodes].filter((node) => node.children).map((node) => [this.mountedPath(node), node])
        )
        const files = incremental ? this.mountedFiles : new Map(this.mountedFiles)
        const apiFiles = new Map(
            [...previousNodes]
                .filter((node) => !node.children && node.parent?.parent === this.api)
                .map((node) => [this.mountedPath(node), node])
        )
        for (const node of previousNodes) {
            node.children?.clear()
        }
        if (!incremental) {
            this.references.clear()
            this.projectNodes.clear()
            this.mountedFiles.clear()
            this.registerDirectory(this.files, [])
            this.mountApiDirectories(directories)
        } else {
            for (const entry of entries) {
                const extension = this.extension(entry)
                // A content-type change gives the entry a new extension, so the node under the old
                // extension is not reused below and must be retired here to avoid a stale duplicate.
                for (const candidate of ['.md', '.sql', '.json']) {
                    const identity = this.fileIdentity(entry, candidate)
                    const existing = files.get(identity)
                    if (!existing) {
                        continue
                    }
                    existing.parent!.children!.delete(existing.name)
                    this.references.delete(this.mountedPath(existing))
                    if (candidate !== extension) {
                        files.delete(identity)
                        this.projectNodes.delete(existing)
                        existing.removed = true
                    }
                }
            }
        }
        for (const entry of entries.filter((item) => item.type === 'folder' && item.user_access_level !== 'none')) {
            const parts = splitPath(entry.path)
            this.registerDirectory(this.parent(parts, this.files, directories), parts, entry)
        }
        const mountedApiPaths = new Set<string>()
        for (const entry of entries) {
            if (entry.type === 'folder' || entry.user_access_level === 'none') {
                continue
            }
            const parts = splitPath(entry.path)
            const basename = terminalFilename(parts.pop() ?? 'Untitled')
            const parent = this.parent(parts, this.files, directories)
            const extension = this.extension(entry)
            let name = basename.endsWith(extension) ? basename : `${basename}${extension}`
            if (parent.children!.has(name)) {
                name = `${basename}~${entry.id}${extension}`
            }
            let duplicate = 1
            while (parent.children!.has(name)) {
                name = `${basename}~${entry.id}-${duplicate++}${extension}`
            }
            const access = entry.user_access_level
            const writable =
                !!this.objectApi(entry) && (access === null || ['editor', 'manager'].includes(access ?? ''))
            const file = this.mountFile(
                name,
                parent,
                extension === '.md'
                    ? (signal) => this.notebook(entry, signal)
                    : (signal) => this.document(entry, writable, signal, extension === '.sql'),
                writable,
                files.get(this.fileIdentity(entry, extension))
            )
            this.mountedFiles.set(this.fileIdentity(entry, extension), file)
            file.writeKey = JSON.stringify([entry.type, entry.ref ?? entry.id])
            this.projectNodes.set(file, { parts: splitPath(entry.path), entry, extension })
            file.rename = (parent, name) => this.move(file, parent, name)
            file.remove = () => this.remove(file)
            this.references.set(`/posthog/files/${[...parts.map(terminalFilename), name].join('/')}`, entry)
            const type = this.mountDirectory(terminalFilename(entry.type ?? 'unknown'), this.api, directories)
            type.loadChildren = () => this.ensureDirectory(type)
            const apiName = `${terminalFilename(entry.ref ?? entry.id)}.json`
            const apiPath = `${this.mountedPath(type)}/${apiName}`
            if (!mountedApiPaths.has(apiPath)) {
                mountedApiPaths.add(apiPath)
                const apiFile = this.mountFile(
                    apiName,
                    type,
                    (signal) => this.document(entry, writable, signal),
                    writable,
                    apiFiles.get(apiPath) ?? type.children!.get(apiName)
                )
                apiFile.writeKey = file.writeKey
                this.references.set(apiPath, entry)
            }
        }
        if (!incremental) {
            const currentNodes = this.mountedNodes()
            for (const node of previousNodes) {
                if (!currentNodes.has(node)) {
                    node.removed = true
                    this.loadedDirectories.delete(node)
                }
            }
        }
    }

    private fileIdentity(entry: FileSystemApi, extension: string): string {
        return JSON.stringify([entry.id, entry.type, entry.ref, extension])
    }

    private extension(entry: FileSystemApi): string {
        if (!this.validReference(entry)) {
            return '.json'
        }
        const contentType =
            entry.meta && typeof entry.meta === 'object' && 'content_type' in entry.meta
                ? entry.meta.content_type
                : undefined
        return entry.type === 'notebook' && contentType === 'text/markdown'
            ? '.md'
            : entry.type === 'insight' && contentType === 'application/sql'
              ? '.sql'
              : '.json'
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
