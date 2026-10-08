import { NinePReader, NinePWriter } from './ninepCodec'
import { NinePServer } from './ninepServer'
import { MAX_TERMINAL_FILE_BYTES, TerminalFilesystem } from './terminalFilesystem'

describe('PostHog 9P filesystem', () => {
    const encoder = new TextEncoder()
    const decoder = new TextDecoder()
    let filesystem: TerminalFilesystem
    let server: NinePServer
    let saved: string
    let failSave: boolean
    let errors: string[]

    async function request(type: number, body = new NinePWriter()): Promise<{ type: number; body: NinePReader }> {
        const bytes = await new Promise<Uint8Array>((resolve) => server.handle(body.frame(type, 42), resolve))
        const reader = new NinePReader(bytes)
        expect(reader.number(4)).toBe(bytes.length)
        const responseType = reader.number(1)
        expect(reader.number(2)).toBe(42)
        return { type: responseType, body: reader }
    }

    async function walk(name: string, fid = 2): Promise<void> {
        const response = await request(110, new NinePWriter().number(1, 4).number(fid, 4).number(1, 2).string(name))
        expect(response.type).toBe(111)
    }

    async function open(flags: number, fid = 2): Promise<number> {
        return (await request(12, new NinePWriter().number(fid, 4).number(flags, 4))).type
    }

    async function write(text: string, offset = 0): Promise<number> {
        const data = encoder.encode(text)
        return (await request(118, new NinePWriter().number(2, 4).number(offset, 8).number(data.length, 4).data(data)))
            .type
    }

    beforeEach(async () => {
        saved = '# café 🦔\n'
        failSave = false
        errors = []
        filesystem = new TerminalFilesystem()
        filesystem.file(
            'note.md',
            filesystem.root,
            async () => ({
                bytes: encoder.encode(saved),
                save: async (data) => {
                    if (failSave) {
                        throw new Error('Conflict')
                    }
                    saved = decoder.decode(data)
                },
            }),
            true
        )
        filesystem.text('view.json', filesystem.root, '{}')
        server = new NinePServer(filesystem, (error) => errors.push(error))
        await request(100, new NinePWriter().number(65536, 4).string('9P2000.L'))
        await request(104, new NinePWriter().number(1, 4).number(0xffffffff, 4).string('root').string('').number(0, 4))
        await walk('note.md')
    })

    it('reads UTF-8 by byte offset, and opens fresh content after a remote edit', async () => {
        const load = jest.spyOn(filesystem.root.children!.get('note.md')!, 'open')
        const stat = await request(24, new NinePWriter().number(2, 4).number(0x7ff, 8))
        expect(stat.type).toBe(25)
        stat.body.data(49)
        expect(stat.body.number(8)).toBe(0)
        expect(load).not.toHaveBeenCalled()
        expect(await open(0)).toBe(13)
        expect(load).toHaveBeenCalledTimes(1)
        const response = await request(116, new NinePWriter().number(2, 4).number(2, 8).number(1024, 4))
        expect(decoder.decode(response.body.data(response.body.number(4)))).toBe('café 🦔\n')
        await request(120, new NinePWriter().number(2, 4))
        saved = 'Changed in PostHog'
        await walk('note.md')
        await open(0)
        const fresh = await request(116, new NinePWriter().number(2, 4).number(0, 8).number(1024, 4))
        expect(decoder.decode(fresh.body.data(fresh.body.number(4)))).toBe(saved)
    })

    it.each([76, 122])(
        'unlinks through message %i without reopening deleted files or losing active edits',
        async (type) => {
            const note = filesystem.root.children!.get('note.md')!
            note.remove = jest.fn(async () => {
                filesystem.root.children!.delete(note.name)
                note.removed = true
            })
            const remove = (): Promise<{ type: number; body: NinePReader }> =>
                request(
                    type,
                    type === 76
                        ? new NinePWriter().number(1, 4).string('note.md').number(0, 4)
                        : new NinePWriter().number(3, 4)
                )
            await open(1)
            await write('Edit')
            await walk('note.md', 3)
            expect((await remove()).body.number(4)).toBe(16)
            expect(note.remove).not.toHaveBeenCalled()
            await request(120, new NinePWriter().number(2, 4))
            expect(saved).toContain('Edit')
            await walk('note.md', 2)
            await open(0)
            await walk('note.md', 3)
            await walk('note.md', 4)
            expect((await remove()).type).toBe(type + 1)
            const read = await request(116, new NinePWriter().number(2, 4).number(0, 8).number(1024, 4))
            expect(decoder.decode(read.body.data(read.body.number(4)))).toBe(saved)
            expect(await open(0, 4)).toBe(7)
            expect(filesystem.root.children!.has('note.md')).toBe(false)
        }
    )

    it('rejects nonempty folders, mismatched removal flags, and read-only mount entries', async () => {
        const folder = filesystem.directory('folder', filesystem.root)
        folder.remove = jest.fn(async () => {})
        folder.loadChildren = async () => {
            filesystem.text('child', folder, '')
        }
        const remove = (name: string, flags: number): Promise<{ type: number; body: NinePReader }> =>
            request(76, new NinePWriter().number(1, 4).string(name).number(flags, 4))
        expect((await remove('folder', 0x200)).body.number(4)).toBe(39)
        expect((await remove('folder', 0)).body.number(4)).toBe(21)
        expect((await remove('note.md', 0x200)).body.number(4)).toBe(20)
        expect((await remove('view.json', 0)).body.number(4)).toBe(30)
        expect((await remove('missing', 0)).body.number(4)).toBe(2)
        expect(folder.remove).not.toHaveBeenCalled()
    })

    it('checks an unloaded destination before renaming over an existing file', async () => {
        const folder = filesystem.directory('folder', filesystem.root)
        folder.mkdir = jest.fn()
        folder.loadChildren = async () => {
            filesystem.text('taken.json', folder, '{}')
        }
        const note = filesystem.root.children!.get('note.md')!
        note.rename = jest.fn()
        await walk('folder', 3)
        const response = await request(20, new NinePWriter().number(2, 4).number(3, 4).string('taken.json'))
        expect(response.type).toBe(7)
        expect(response.body.number(4)).toBe(17)
        expect(note.rename).not.toHaveBeenCalled()
    })

    it.each([50, 120])('commits complete, truncated content on message %i', async (operation) => {
        expect(await open(513)).toBe(13)
        await write('short')
        expect(saved).toBe('# café 🦔\n')
        expect((await request(operation, new NinePWriter().number(2, 4).number(0, 4))).type).toBe(operation + 1)
        expect(saved).toBe('short')
    })

    it('preserves failed edits in recovery and returns EIO without overwriting the remote file', async () => {
        await open(513)
        await write('My edit')
        failSave = true
        const response = await request(120, new NinePWriter().number(2, 4))
        expect(response.type).toBe(7)
        expect(response.body.number(4)).toBe(5)
        expect(saved).toBe('# café 🦔\n')
        const recovered = [...filesystem.recovery.children!.values()][0]
        expect(decoder.decode((await recovered.open!()).bytes)).toBe('My edit')
        expect(errors[0]).toContain(`/posthog/recovery/${recovered.name}`)
        expect(errors[0]).toContain('Conflict')
        await walk('note.md')
        expect(await open(1)).toBe(13)
    })

    it.each([2, 3])('accepts Linux truncation through open or path fid %i', async (fid) => {
        await open(1)
        await walk('note.md', 3)
        const response = await request(
            26,
            new NinePWriter()
                .number(fid, 4)
                .number(0x68, 4)
                .number(0, 4)
                .number(0xffffffff, 4)
                .number(0xffffffff, 4)
                .number(0, 8)
                .number(0, 8)
                .number(0, 8)
                .number(0, 8)
                .number(0, 8)
        )
        expect(response.type).toBe(27)
        await write('Truncated')
        await request(120, new NinePWriter().number(2, 4))
        expect(saved).toBe('Truncated')
    })

    it('commits a path-only truncate without keeping a writer lock', async () => {
        const response = await request(
            26,
            new NinePWriter().number(2, 4).number(8, 4).data(new Uint8Array(12)).number(0, 8)
        )
        expect(response.type).toBe(27)
        expect(saved).toBe('')
        expect(await open(1)).toBe(13)
        await write('After truncate')
        await request(120, new NinePWriter().number(2, 4))
        expect(saved).toBe('After truncate')
    })

    it('rejects concurrent writers, writes through a read descriptor, and writes to read-only objects', async () => {
        await open(1)
        await walk('note.md', 3)
        expect(await open(1, 3)).toBe(7)
        await request(120, new NinePWriter().number(2, 4))
        await walk('note.md')
        await open(0)
        expect(await write('bad')).toBe(7)
        await walk('view.json', 4)
        expect(await open(1, 4)).toBe(7)
        expect(saved).toBe('# café 🦔\n')
    })

    it('assembles a chunked write from many packets, and keeps truncation and sparse gaps correct', async () => {
        await open(1 | 512)
        const chunk = 'abcdefgh'
        let expected = ''
        for (let index = 0; index < 200; index++) {
            expect(await write(chunk, expected.length)).toBe(119)
            expected += chunk
        }
        await request(120, new NinePWriter().number(2, 4))
        expect(saved).toBe(expected)

        await walk('note.md')
        await open(1)
        await write('ZZZZ', 8)
        await request(120, new NinePWriter().number(2, 4))
        expect(saved).toBe(`${expected.slice(0, 8)}ZZZZ${expected.slice(12)}`)

        await walk('note.md')
        await open(1 | 512)
        await write('abcdefghij')
        await request(26, new NinePWriter().number(2, 4).number(8, 4).data(new Uint8Array(12)).number(2, 8))
        await write('Z', 4)
        await request(120, new NinePWriter().number(2, 4))
        expect(saved).toBe('ab\u0000\u0000Z')
    })

    it('frames a read that outgrows the response buffer without corrupting it', async () => {
        saved = 'hedgehog \u{1F994} '.repeat(4000)
        const body = encoder.encode(saved)
        expect(await open(0)).toBe(13)
        const response = await request(116, new NinePWriter().number(2, 4).number(0, 8).number(body.length, 4))
        const returned = response.body.data(response.body.number(4))
        expect(returned.length).toBe(body.length)
        expect(decoder.decode(returned)).toBe(saved)
    })

    it('rejects oversized sparse writes without allocating their requested size', async () => {
        await open(1)
        expect(await write('x', MAX_TERMINAL_FILE_BYTES)).toBe(7)
        await request(120, new NinePWriter().number(2, 4))
        expect(saved).toBe('# café 🦔\n')
    })

    it.each([12, 24])('continues serving requests when a type %s reply throws', async (type) => {
        let replied!: () => void
        const attempted = new Promise<void>((resolve) => (replied = resolve))
        const brokenReply = jest.fn(() => {
            replied()
            throw new RangeError('Guest buffer is outside memory')
        })
        server.handle(new NinePWriter().number(2, 4).number(0, 8).frame(type, 10), brokenReply)
        await attempted
        expect((await request(120, new NinePWriter().number(2, 4))).type).toBe(121)
        expect(brokenReply).toHaveBeenCalledTimes(1)
    })

    it('cancels a pending open without blocking flush or replying to its reused tag', async () => {
        let reading!: () => void
        const started = new Promise<void>((resolve) => (reading = resolve))
        filesystem.file('slow.json', filesystem.root, async (signal) => {
            reading()
            await new Promise<void>((_, reject) =>
                signal!.addEventListener('abort', () => reject(signal!.reason), { once: true })
            )
            return { bytes: encoder.encode('never returned') }
        })
        await walk('slow.json', 3)
        const originalReply = jest.fn()
        server.handle(new NinePWriter().number(3, 4).number(0, 4).frame(12, 10), originalReply)
        await started
        expect((await request(108, new NinePWriter().number(10, 2))).type).toBe(109)
        const bytes = await new Promise<Uint8Array>((resolve) =>
            server.handle(new NinePWriter().number(1, 4).number(0x7ff, 8).frame(24, 10), resolve)
        )
        const response = new NinePReader(bytes)
        response.number(4)
        expect(response.number(1)).toBe(25)
        expect(response.number(2)).toBe(10)
        expect(originalReply).not.toHaveBeenCalled()
        expect((await request(120, new NinePWriter().number(3, 4))).type).toBe(121)
    })

    it('shares writer locks across mounted aliases, including truncation and deletion', async () => {
        const note = filesystem.root.children!.get('note.md')!
        note.writeKey = 'notebook:note'
        const alias = filesystem.file('alias.json', filesystem.root, note.open!, true)
        alias.writeKey = note.writeKey
        alias.remove = jest.fn(async () => {})
        await open(1)
        await walk('alias.json', 3)
        expect(await open(1, 3)).toBe(7)
        const truncate = await request(
            26,
            new NinePWriter().number(3, 4).number(8, 4).data(new Uint8Array(12)).number(0, 8)
        )
        expect(truncate.body.number(4)).toBe(16)
        const remove = await request(76, new NinePWriter().number(1, 4).string('alias.json').number(0, 4))
        expect(remove.body.number(4)).toBe(16)
        expect(alias.remove).not.toHaveBeenCalled()
        await request(120, new NinePWriter().number(2, 4))
        expect(await open(1, 3)).toBe(13)
    })

    it('appends to freshly loaded content even when the guest sends a stale size as its offset', async () => {
        expect(await open(1025)).toBe(13)
        await write('Appended', 0)
        await write(' twice', 8)
        await request(120, new NinePWriter().number(2, 4))
        expect(saved).toBe('# café 🦔\nAppended twice')
    })

    it('lists unrelated directories while an API save is pending', async () => {
        let saving!: () => void
        let finish!: () => void
        const started = new Promise<void>((resolve) => (saving = resolve))
        const pending = new Promise<void>((resolve) => (finish = resolve))
        filesystem.file(
            'slow-write.json',
            filesystem.root,
            async () => ({
                bytes: encoder.encode('{}'),
                save: async () => {
                    saving()
                    await pending
                },
            }),
            true
        )
        await walk('slow-write.json')
        await open(513)
        await write('{}')
        const closed = new Promise<Uint8Array>((resolve) =>
            server.handle(new NinePWriter().number(2, 4).frame(120, 10), resolve)
        )
        await started
        try {
            expect((await request(24, new NinePWriter().number(1, 4).number(0x7ff, 8))).type).toBe(25)
            expect((await request(40, new NinePWriter().number(1, 4).number(0, 8).number(1024, 4))).type).toBe(41)
            await walk('view.json', 3)
        } finally {
            finish()
            await closed
        }
    })

    it('keeps directory offsets stable across paginated readdir', async () => {
        const names: string[] = []
        let offset = 0
        while (true) {
            const response = await request(40, new NinePWriter().number(1, 4).number(offset, 8).number(45, 4))
            const length = response.body.number(4)
            if (!length) {
                break
            }
            const entry = new NinePReader(response.body.data(length))
            entry.data(13)
            offset = entry.number(8)
            entry.number(1)
            names.push(entry.string())
        }
        expect(names).toEqual(['.', '..', 'recovery', 'note.md', 'view.json'])
    })

    it('does not drop later entries when a listed one is removed between pages', async () => {
        const names: string[] = []
        let offset = 0
        while (true) {
            const response = await request(40, new NinePWriter().number(1, 4).number(offset, 8).number(45, 4))
            const length = response.body.number(4)
            if (!length) {
                break
            }
            const entry = new NinePReader(response.body.data(length))
            entry.data(13)
            offset = entry.number(8)
            entry.number(1)
            const name = entry.string()
            names.push(name)
            if (name === 'recovery') {
                filesystem.root.children!.delete('recovery')
            }
        }
        expect(names).toEqual(['.', '..', 'recovery', 'note.md', 'view.json'])
    })

    it('shows a fresh directory when a listing restarts from the beginning', async () => {
        const read = async (offset: number): Promise<string> => {
            const response = await request(40, new NinePWriter().number(1, 4).number(offset, 8).number(45, 4))
            const length = response.body.number(4)
            if (!length) {
                return ''
            }
            const entry = new NinePReader(response.body.data(length))
            entry.data(13)
            entry.number(8)
            entry.number(1)
            return entry.string()
        }
        await read(0)
        filesystem.text('added.json', filesystem.root, '{}')
        expect(await read(5)).toBe('')
        await read(0)
        expect(await read(5)).toBe('added.json')
    })
})
