import { NinePReader, NinePWriter } from './ninepCodec'
import { MAX_TERMINAL_FILE_BYTES, TerminalFile, TerminalFilesystem, TerminalNode } from './terminalFilesystem'

class FilesystemError extends Error {
    constructor(readonly errno: number) {
        super(`Filesystem error ${errno}`)
    }
}

interface Fid {
    node: TerminalNode
    file?: TerminalFile
    dirty?: boolean
    writing?: boolean
    failed?: boolean
}

function qid(writer: NinePWriter, node: TerminalNode): NinePWriter {
    return writer
        .number(node.children ? 128 : 0, 1)
        .number(0, 4)
        .number(node.id, 8)
}

export class NinePServer {
    private fids = new Map<number, Fid>()
    private writers = new Set<number>()
    private queue: Promise<void> = Promise.resolve()
    private messageSize = 256 * 1024

    constructor(
        readonly filesystem: TerminalFilesystem,
        private onSaveError: (message: string) => void
    ) {}

    // Serialize requests so a close cannot overtake an asynchronous read or save on the same fid.
    handle = (bytes: Uint8Array, reply: (bytes: Uint8Array) => void): void => {
        this.queue = this.queue.then(async () => {
            const reader = new NinePReader(bytes)
            let tag = 0xffff
            try {
                const size = reader.number(4)
                const type = reader.number(1)
                tag = reader.number(2)
                if (size !== bytes.length || size > this.messageSize) {
                    throw new FilesystemError(22)
                }
                const result = await this.request(type, reader)
                reply(result.frame(type + 1, tag))
            } catch (error) {
                reply(new NinePWriter().number(error instanceof FilesystemError ? error.errno : 5, 4).frame(7, tag))
            }
        })
    }

    private fid(id: number): Fid {
        const fid = this.fids.get(id)
        if (!fid) {
            throw new FilesystemError(9)
        }
        return fid
    }

    private async open(fid: Fid, flags: number): Promise<void> {
        if (fid.node.children) {
            if (flags & 3) {
                throw new FilesystemError(21)
            }
            return
        }
        const writing = !!(flags & 3)
        if (writing && (!fid.node.writable || this.writers.has(fid.node.id))) {
            throw new FilesystemError(fid.node.writable ? 16 : 30)
        }
        fid.file = await fid.node.open!()
        if (writing && !fid.file.save) {
            throw new FilesystemError(30)
        }
        fid.writing = writing
        if (writing) {
            this.writers.add(fid.node.id)
        }
        if (writing && flags & 512) {
            fid.file.bytes = new Uint8Array()
            fid.dirty = true
        }
        fid.node.size = fid.file.bytes.length
    }

    private async save(fid: Fid): Promise<void> {
        if (!fid.dirty || !fid.file?.save) {
            return
        }
        if (fid.failed) {
            throw new FilesystemError(5)
        }
        try {
            await fid.file.save(fid.file.bytes)
            fid.dirty = false
            fid.node.size = fid.file.bytes.length
        } catch {
            fid.failed = true
            const recovery = this.filesystem.recover(fid.node, fid.file.bytes)
            this.onSaveError(
                `Could not save ${fid.node.name}. Check your access or concurrent edits. Your edit is in ${recovery}.`
            )
            throw new FilesystemError(5)
        }
    }

    private async request(type: number, reader: NinePReader): Promise<NinePWriter> {
        const result = new NinePWriter()
        switch (type) {
            case 100: {
                this.messageSize = Math.min(reader.number(4), 256 * 1024)
                const version = reader.string()
                return result.number(this.messageSize, 4).string(version === '9P2000.L' ? version : 'unknown')
            }
            case 104: {
                const id = reader.number(4)
                reader.number(4)
                reader.string()
                const mount = reader.string()
                if (mount && mount !== '/') {
                    throw new FilesystemError(2)
                }
                this.fids.set(id, { node: this.filesystem.root })
                return qid(result, this.filesystem.root)
            }
            case 108:
                return result
            case 110: {
                let node = this.fid(reader.number(4)).node
                const newId = reader.number(4)
                const count = reader.number(2)
                const walked: TerminalNode[] = []
                for (let i = 0; i < count; i++) {
                    const name = reader.string()
                    const next = name === '..' ? (node.parent ?? node) : name === '.' ? node : node.children?.get(name)
                    if (!next) {
                        if (!walked.length) {
                            throw new FilesystemError(2)
                        }
                        break
                    }
                    node = next
                    walked.push(node)
                }
                this.fids.set(newId, { node })
                result.number(walked.length, 2)
                walked.forEach((entry) => qid(result, entry))
                return result
            }
            case 12: {
                const fid = this.fid(reader.number(4))
                await this.open(fid, reader.number(4))
                return qid(result, fid.node).number(this.messageSize - 24, 4)
            }
            case 24: {
                const fid = this.fid(reader.number(4))
                const node = fid.node
                // Like procfs, unopened API files report zero bytes without fetching their contents.
                result.number(0x7ff, 8)
                qid(result, node)
                result.number(node.children ? 0o40555 : node.writable ? 0o100644 : 0o100444, 4)
                result
                    .number(0, 4)
                    .number(0, 4)
                    .number(node.children ? 2 : 1, 8)
                    .number(0, 8)
                result
                    .number(node.size, 8)
                    .number(4096, 8)
                    .number(Math.ceil(node.size / 512), 8)
                for (let i = 0; i < 10; i++) {
                    result.number(0, 8)
                }
                return result
            }
            case 40: {
                const node = this.fid(reader.number(4)).node
                const offset = reader.number(8)
                const count = Math.min(reader.number(4), this.messageSize - 11)
                if (!node.children) {
                    throw new FilesystemError(20)
                }
                const entries = [node, node.parent ?? node, ...node.children.values()]
                const data = new NinePWriter()
                let length = 0
                for (let i = offset; i < entries.length; i++) {
                    const entry = entries[i]
                    const bytes = qid(new NinePWriter(), entry)
                        .number(i + 1, 8)
                        .number(entry.children ? 4 : 8, 1)
                        .string(i === 0 ? '.' : i === 1 ? '..' : entry.name)
                        .build()
                    if (length + bytes.length > count) {
                        break
                    }
                    data.data(bytes)
                    length += bytes.length
                }
                return result.number(length, 4).data(data.build())
            }
            case 116: {
                const fid = this.fid(reader.number(4))
                const offset = reader.number(8)
                const count = Math.min(reader.number(4), this.messageSize - 11)
                if (!fid.file) {
                    throw new FilesystemError(9)
                }
                const data = fid.file.bytes.slice(offset, offset + count)
                return result.number(data.length, 4).data(data)
            }
            case 118: {
                const fid = this.fid(reader.number(4))
                const offset = reader.number(8)
                const count = reader.number(4)
                if (!fid.writing || !fid.file || fid.failed) {
                    throw new FilesystemError(9)
                }
                if (offset + count > MAX_TERMINAL_FILE_BYTES) {
                    throw new FilesystemError(27)
                }
                const bytes = new Uint8Array(Math.max(fid.file.bytes.length, offset + count))
                bytes.set(fid.file.bytes)
                bytes.set(reader.data(count), offset)
                fid.file.bytes = bytes
                fid.dirty = true
                fid.node.size = bytes.length
                return result.number(count, 4)
            }
            case 26: {
                const fid = this.fid(reader.number(4))
                const valid = reader.number(4)
                reader.data(12)
                const size = reader.number(8)
                // Linux includes mtime and ctime when truncating through shell redirection.
                if (valid & ~0x1f8) {
                    throw new FilesystemError(95)
                }
                if (valid & 8) {
                    if (size > MAX_TERMINAL_FILE_BYTES) {
                        throw new FilesystemError(27)
                    }
                    if (!fid.file) {
                        await this.open(fid, 1)
                    }
                    if (!fid.writing || !fid.file) {
                        throw new FilesystemError(30)
                    }
                    const bytes = new Uint8Array(size)
                    bytes.set(fid.file.bytes.subarray(0, size))
                    fid.file.bytes = bytes
                    fid.node.size = size
                    fid.dirty = true
                }
                return result
            }
            case 50:
                await this.save(this.fid(reader.number(4)))
                return result
            case 120: {
                const id = reader.number(4)
                const fid = this.fid(id)
                try {
                    await this.save(fid)
                } finally {
                    if (fid.writing) {
                        this.writers.delete(fid.node.id)
                    }
                    this.fids.delete(id)
                }
                return result
            }
            case 8:
                return result
                    .number(0x01021997, 4)
                    .number(4096, 4)
                    .number(0, 8)
                    .number(0, 8)
                    .number(0, 8)
                    .number(0, 8)
                    .number(0, 8)
                    .number(0, 8)
                    .number(255, 4)
            default:
                throw new FilesystemError(95)
        }
    }
}
