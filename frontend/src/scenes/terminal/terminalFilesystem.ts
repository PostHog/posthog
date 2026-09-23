export interface TerminalFile {
    bytes: Uint8Array
    save?: (bytes: Uint8Array) => Promise<void>
}

export interface TerminalNode {
    id: number
    name: string
    parent?: TerminalNode
    children?: Map<string, TerminalNode>
    open?: (signal?: AbortSignal) => Promise<TerminalFile>
    size: number
    writable: boolean
    writeKey?: string
    mkdir?: (name: string) => Promise<TerminalNode>
    rename?: (parent: TerminalNode, name: string) => Promise<void>
    remove?: () => Promise<void>
    removed?: boolean
}

export class FilesystemError extends Error {
    constructor(readonly errno: number) {
        super(`Filesystem error ${errno}`)
    }
}

export const MAX_TERMINAL_FILE_BYTES = 4 * 1024 * 1024

export class TerminalFilesystem {
    private nextId = 1
    readonly root: TerminalNode = this.directory('')
    readonly recovery = this.directory('recovery', this.root)

    directory(name: string, parent?: TerminalNode): TerminalNode {
        const existing = parent?.children?.get(name)
        if (existing?.children) {
            return existing
        }
        const node: TerminalNode = { id: this.nextId++, name, parent, children: new Map(), size: 0, writable: false }
        parent?.children?.set(name, node)
        return node
    }

    file(
        name: string,
        parent: TerminalNode,
        open: (signal?: AbortSignal) => Promise<TerminalFile>,
        writable = false
    ): TerminalNode {
        const node: TerminalNode = { id: this.nextId++, name, parent, open, size: 0, writable }
        parent.children?.set(name, node)
        return node
    }

    text(name: string, parent: TerminalNode, text: string): TerminalNode {
        const bytes = new TextEncoder().encode(text)
        const node = this.file(name, parent, async () => ({ bytes }))
        node.size = bytes.length
        return node
    }

    recover(node: TerminalNode, bytes: Uint8Array): string {
        const name = `${node.id}-${this.nextId}-${node.name}`
        const copy = bytes.slice()
        this.file(name, this.recovery, async () => ({ bytes: copy })).size = copy.length
        return `/posthog/recovery/${name}`
    }
}
