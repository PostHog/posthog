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
        expect(await open(0)).toBe(13)
        const response = await request(116, new NinePWriter().number(2, 4).number(2, 8).number(1024, 4))
        expect(decoder.decode(response.body.data(response.body.number(4)))).toBe('café 🦔\n')
        await request(120, new NinePWriter().number(2, 4))
        saved = 'Changed in PostHog'
        await walk('note.md')
        await open(0)
        const fresh = await request(116, new NinePWriter().number(2, 4).number(0, 8).number(1024, 4))
        expect(decoder.decode(fresh.body.data(fresh.body.number(4)))).toBe(saved)
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
        await walk('note.md')
        expect(await open(1)).toBe(13)
    })

    it('accepts the size and timestamp flags Linux sends when truncating a file', async () => {
        await open(1)
        const response = await request(
            26,
            new NinePWriter()
                .number(2, 4)
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

    it('rejects oversized sparse writes without allocating their requested size', async () => {
        await open(1)
        expect(await write('x', MAX_TERMINAL_FILE_BYTES)).toBe(7)
        await request(120, new NinePWriter().number(2, 4))
        expect(saved).toBe('# café 🦔\n')
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
})
