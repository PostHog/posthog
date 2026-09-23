import apiMutator from 'lib/api-orval-mutator'

import { fileSystemCreate, fileSystemDestroy, fileSystemList, fileSystemRetrieve } from '~/generated/core/api'
import type { FileSystemApi } from '~/generated/core/api.schemas'

import { notebooksList, notebooksPartialUpdate, notebooksRetrieve } from 'products/notebooks/frontend/generated/api'
import type { NotebookApi, NotebookMinimalApi } from 'products/notebooks/frontend/generated/api.schemas'

import { NinePReader, NinePWriter } from './ninepCodec'
import { NinePServer } from './ninepServer'
import { PosthogFilesystem, terminalFilename } from './posthogFilesystem'

jest.mock('~/generated/core/api', () => ({
    ...jest.requireActual('~/generated/core/api'),
    fileSystemList: jest.fn(),
    fileSystemCreate: jest.fn(),
    fileSystemDestroy: jest.fn(),
    fileSystemRetrieve: jest.fn(),
}))
jest.mock('lib/api-orval-mutator', () => {
    const mutator = jest.fn()
    return { __esModule: true, default: mutator, apiMutator: mutator }
})
jest.mock('products/notebooks/frontend/generated/api', () => ({
    notebooksRetrieve: jest.fn(),
    notebooksList: jest.fn(),
    notebooksPartialUpdate: jest.fn(),
}))

describe('PostHog filesystem projection', () => {
    const decoder = new TextDecoder()
    const entry = (id: string, path: string, type = 'notebook'): FileSystemApi => ({
        id,
        path,
        type,
        ref: id,
        depth: 2,
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
        last_viewed_at: null,
        user_access_level: 'editor',
    })
    const notebook = {
        short_id: 'note1',
        version: 7,
        user_access_level: 'editor',
        content: {
            type: 'doc',
            content: [{ type: 'ph-markdown-notebook', attrs: { markdown: '# Hello 🦔', nodeId: 'preserved' } }],
        },
    } as NotebookApi
    const notebookIndex: NotebookMinimalApi = {
        ...notebook,
        title: 'Notes',
        deleted: false,
        user_access_level: 'editor',
    }

    beforeEach(() => {
        jest.clearAllMocks()
        jest.mocked(fileSystemList).mockResolvedValue({
            count: 1,
            next: null,
            results: [entry('note1', 'Research/Notes')],
        })
        jest.mocked(notebooksList).mockResolvedValue({
            count: 2,
            next: null,
            results: [notebookIndex, { ...notebookIndex, short_id: 'note2' }],
        })
        jest.mocked(notebooksRetrieve).mockResolvedValue(notebook)
    })

    it('projects markdown without changing the stored path and saves with the version it read', async () => {
        const session = new AbortController()
        const read = new AbortController()
        const fs = new PosthogFilesystem('42', session.signal)
        await fs.load()
        expect(fs.resolveReference('./Notes.md', '/posthog/files/Research', 'notebook')).toBe('note1')
        expect(fs.resolveReference('/posthog/api/notebook/note1.json', '/', 'notebook')).toBe('note1')
        expect(() => fs.resolveReference('./Notes.md', '/posthog/files/Research', 'dashboard')).toThrow(
            'Expected a dashboard'
        )
        expect(notebooksRetrieve).not.toHaveBeenCalled()
        expect(notebooksList).toHaveBeenCalledWith(
            '42',
            { contains: 'markdown-notebook', limit: 500, offset: 0 },
            expect.anything()
        )
        const file = fs.root.children!.get('files')!.children!.get('Research')!.children!.get('Notes.md')!
        expect(file.writable).toBe(true)
        const opened = await file.open!(read.signal)
        expect(decoder.decode(opened.bytes)).toBe('# Hello 🦔')
        read.abort()
        expect(jest.mocked(notebooksRetrieve).mock.calls[0][2]?.signal).not.toBe(session.signal)
        await opened.save!(opened.bytes)
        expect(notebooksPartialUpdate).not.toHaveBeenCalled()
        jest.mocked(notebooksPartialUpdate).mockResolvedValue({ ...notebook, version: 8 })
        await opened.save!(new TextEncoder().encode('# Updated'))
        expect(notebooksPartialUpdate).toHaveBeenCalledWith(
            '42',
            'note1',
            {
                content: {
                    type: 'doc',
                    content: [{ type: 'ph-markdown-notebook', attrs: { markdown: '# Updated', nodeId: 'preserved' } }],
                },
                text_content: '# Updated',
                version: 7,
            },
            expect.objectContaining({ signal: session.signal })
        )
        await opened.save!(new TextEncoder().encode('# Updated'))
        expect(notebooksPartialUpdate).toHaveBeenCalledTimes(1)
        jest.mocked(notebooksPartialUpdate).mockRejectedValue(new Error('Version conflict'))
        await expect(opened.save!(new TextEncoder().encode('Conflict'))).rejects.toThrow('Version conflict')
        expect(jest.mocked(notebooksPartialUpdate).mock.calls[1][2]?.version).toBe(8)
    })

    it('refreshes through retained directory and file handles without saving deleted objects', async () => {
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        await fs.load()
        const note = fs.root.children!.get('files')!.children!.get('Research')!.children!.get('Notes.md')!
        const apiNote = fs.root.children!.get('api')!.children!.get('notebook')!.children!.get('note1.json')!
        const opened = await note.open!()
        const openedApi = await apiNote.open!()
        const server = new NinePServer(fs, jest.fn())
        const request = async (type: number, body: NinePWriter): Promise<{ type: number; body: NinePReader }> => {
            const bytes = await new Promise<Uint8Array>((resolve) => server.handle(body.frame(type, 1), resolve))
            const response = new NinePReader(bytes)
            response.number(4)
            const responseType = response.number(1)
            response.number(2)
            return { type: responseType, body: response }
        }
        await request(104, new NinePWriter().number(1, 4).number(0xffffffff, 4).string('root').string(''))
        await request(110, new NinePWriter().number(1, 4).number(2, 4).number(2, 2).string('files').string('Research'))
        jest.mocked(fileSystemList).mockResolvedValue({
            count: 2,
            next: null,
            results: [entry('note1', 'Research/Notes'), entry('note2', 'Research/New')],
        })
        jest.mocked(notebooksRetrieve).mockClear()
        await fs.load()
        expect(fs.root.children!.get('files')!.children!.get('Research')!.children!.get('Notes.md')).toBe(note)
        expect(fs.root.children!.get('api')!.children!.get('notebook')!.children!.get('note1.json')).toBe(apiNote)
        expect(
            (await request(110, new NinePWriter().number(2, 4).number(3, 4).number(1, 2).string('New.md'))).type
        ).toBe(111)
        jest.mocked(fileSystemCreate).mockResolvedValue(entry('folder', 'Research/New folder', 'folder'))
        expect((await request(72, new NinePWriter().number(2, 4).string('New folder'))).type).toBe(73)
        expect(fileSystemCreate).toHaveBeenLastCalledWith(
            '42',
            { path: 'Research/New folder', type: 'folder' },
            expect.anything()
        )
        jest.mocked(fileSystemList).mockResolvedValue({ count: 1, next: null, results: [entry('note1', 'Renamed')] })
        await fs.load()
        const renamed = fs.root.children!.get('files')!.children!.get('Renamed.md')!
        expect(renamed).toBe(note)
        expect(fs.resolveReference('Renamed.md', '/posthog/files', 'notebook')).toBe('note1')
        expect(() => fs.resolveReference('Research/Notes.md', '/posthog/files', 'notebook')).toThrow('No project file')
        jest.mocked(notebooksPartialUpdate).mockResolvedValue({ ...notebook, version: 8 })
        await opened.save!(new TextEncoder().encode('Save after refresh'))
        expect(notebooksPartialUpdate).toHaveBeenCalledWith(
            '42',
            'note1',
            expect.objectContaining({ version: 7, text_content: 'Save after refresh' }),
            expect.anything()
        )
        jest.mocked(fileSystemList).mockResolvedValue({ count: 0, next: null, results: [] })
        await fs.load()
        jest.mocked(notebooksPartialUpdate).mockClear()
        await expect(opened.save!(new TextEncoder().encode('Deleted notebook'))).rejects.toMatchObject({ errno: 116 })
        await expect(openedApi.save!(new TextEncoder().encode('{"title":"Deleted notebook"}'))).rejects.toMatchObject({
            errno: 116,
        })
        expect(notebooksPartialUpdate).not.toHaveBeenCalled()
        expect(notebooksRetrieve).not.toHaveBeenCalled()
    })

    it.each([
        ['markdown', 'read'],
        ['markdown', 'session'],
        ['JSON', 'read'],
        ['JSON', 'session'],
    ])('cancels a pending %s read when the %s ends', async (format, aborted) => {
        const session = new AbortController()
        const read = new AbortController()
        const fs = new PosthogFilesystem('42', session.signal)
        await fs.load()
        jest.mocked(notebooksRetrieve).mockImplementationOnce(
            (_, __, options) =>
                new Promise((_, reject) => {
                    options!.signal!.addEventListener('abort', () => reject(new Error('Read canceled')), { once: true })
                })
        )
        const node =
            format === 'markdown'
                ? fs.root.children!.get('files')!.children!.get('Research')!.children!.get('Notes.md')!
                : fs.root.children!.get('api')!.children!.get('notebook')!.children!.get('note1.json')!
        const result = node.open!(read.signal)
        ;(aborted === 'read' ? read : session).abort()
        await expect(result).rejects.toThrow('Read canceled')
    })

    it('removes project references and empty folders only after the API succeeds, without loading bodies', async () => {
        jest.mocked(fileSystemList).mockResolvedValue({
            count: 3,
            results: [
                entry('folder', 'Research', 'folder'),
                entry('note1', 'Research/Notes'),
                { ...entry('alias', 'Copy'), ref: 'note1' },
            ],
        })
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        await fs.load()
        const files = fs.root.children!.get('files')!
        const folder = files.children!.get('Research')!
        const note = folder.children!.get('Notes.md')!
        await expect(folder.remove!()).rejects.toMatchObject({ errno: 39 })
        expect(fileSystemDestroy).not.toHaveBeenCalled()
        jest.mocked(fileSystemDestroy).mockRejectedValueOnce({ status: 403 })
        await expect(note.remove!()).rejects.toMatchObject({ errno: 13 })
        expect(fs.resolveReference('Research/Notes.md', '/posthog/files')).toBe('note1')
        jest.mocked(fileSystemDestroy).mockResolvedValue(undefined)
        await note.remove!()
        expect(fileSystemDestroy).toHaveBeenLastCalledWith('42', 'note1', { recursive: false }, expect.anything())
        expect(folder.children!.size).toBe(0)
        expect(() => fs.resolveReference('Research/Notes.md', '/posthog/files')).toThrow('No project file')
        expect(fs.resolveReference('/posthog/api/notebook/note1.json', '/')).toBe('note1')
        await files.children!.get('Copy.md')!.remove!()
        expect(() => fs.resolveReference('/posthog/api/notebook/note1.json', '/')).toThrow('No project file')
        jest.mocked(fileSystemDestroy).mockRejectedValueOnce({ status: 409 })
        await expect(folder.remove!()).rejects.toMatchObject({ errno: 39 })
        expect(files.children!.get('Research')).toBe(folder)
        await folder.remove!()
        expect(files.children!.has('Research')).toBe(false)
        expect(fileSystemDestroy).toHaveBeenLastCalledWith('42', 'folder', { recursive: false }, expect.anything())
        expect(notebooksRetrieve).not.toHaveBeenCalled()
    })

    it('rejects moves of implicit folders without creating records or changing their contents', async () => {
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        await fs.load()
        const files = fs.root.children!.get('files')!
        const folder = files.children!.get('Research')!
        const note = folder.children!.get('Notes.md')!

        await expect(folder.rename!(files, 'Published')).rejects.toMatchObject({ errno: 95 })
        expect(fileSystemCreate).not.toHaveBeenCalled()
        expect(apiMutator).not.toHaveBeenCalled()
        expect(files.children!.get('Research')).toBe(folder)
        expect(files.children!.has('Published')).toBe(false)
        expect(folder.children!.get('Notes.md')).toBe(note)
        expect(note.parent).toBe(folder)
    })

    it.each(['Notes', 'Notes.md'])(
        'persists mkdir and moves of %s, preserves open files, and refuses replacement and cycles',
        async (storedName) => {
            jest.mocked(fileSystemList).mockResolvedValue({
                count: 2,
                results: [entry('research', 'Research', 'folder'), entry('note1', `Research/${storedName}`)],
            })
            jest.mocked(fileSystemCreate).mockImplementation(async (_, body) => entry('created', body.path, 'folder'))
            jest.mocked(apiMutator).mockResolvedValue({})
            const fs = new PosthogFilesystem('42', new AbortController().signal)
            await fs.load()
            const server = new NinePServer(fs, jest.fn())
            const request = async (type: number, body: NinePWriter): Promise<{ type: number; body: NinePReader }> => {
                const bytes = await new Promise<Uint8Array>((resolve) => server.handle(body.frame(type, 1), resolve))
                const response = new NinePReader(bytes)
                response.number(4)
                const responseType = response.number(1)
                response.number(2)
                return { type: responseType, body: response }
            }
            const walk = async (from: number, to: number, name: string): Promise<void> => {
                expect(
                    (await request(110, new NinePWriter().number(from, 4).number(to, 4).number(1, 2).string(name))).type
                ).toBe(111)
            }
            const move = (
                from: number,
                name: string,
                to: number,
                newName: string
            ): Promise<{ type: number; body: NinePReader }> =>
                request(74, new NinePWriter().number(from, 4).string(name).number(to, 4).string(newName))
            await request(
                104,
                new NinePWriter().number(1, 4).number(0xffffffff, 4).string('root').string('').number(0, 4)
            )
            await walk(1, 2, 'files')
            await walk(2, 3, 'Research')
            await walk(3, 4, 'Notes.md')
            const note = fs.root.children!.get('files')!.children!.get('Research')!.children!.get('Notes.md')!
            const opened = await note.open!()
            jest.mocked(notebooksRetrieve).mockClear()
            const mkdir = await request(
                72,
                new NinePWriter().number(2, 4).string('Archive').number(0o755, 4).number(0, 4)
            )
            expect(mkdir.type).toBe(73)
            expect(fileSystemCreate).toHaveBeenCalledWith('42', { path: 'Archive', type: 'folder' }, expect.anything())
            await walk(2, 5, 'Archive')
            expect((await move(3, 'Notes.md', 5, 'Renamed.md')).type).toBe(75)
            expect(apiMutator).toHaveBeenLastCalledWith(
                '/api/projects/42/file_system/note1/move/',
                expect.objectContaining({
                    method: 'POST',
                    body: JSON.stringify({
                        new_path: storedName.endsWith('.md') ? 'Archive/Renamed.md' : 'Archive/Renamed',
                    }),
                })
            )
            expect(fs.resolveReference('Archive/Renamed.md', '/posthog/files', 'notebook')).toBe('note1')
            expect(() => fs.resolveReference('Research/Notes.md', '/posthog/files')).toThrow('No project file')
            expect(fs.root.children!.get('files')!.children!.get('Archive')!.children!.get('Renamed.md')).toBe(note)
            const rename = await request(20, new NinePWriter().number(5, 4).number(2, 4).string('Published'))
            expect(rename.type).toBe(21)
            expect(apiMutator).toHaveBeenLastCalledWith(
                '/api/projects/42/file_system/created/move/',
                expect.objectContaining({
                    body: JSON.stringify({ new_path: 'Published' }),
                })
            )
            expect(fs.resolveReference('Published/Renamed.md', '/posthog/files', 'notebook')).toBe('note1')
            expect(notebooksRetrieve).not.toHaveBeenCalled()
            jest.mocked(notebooksPartialUpdate).mockResolvedValue({ ...notebook, version: 8 })
            await opened.save!(new TextEncoder().encode('Edit after move'))
            expect(notebooksPartialUpdate).toHaveBeenCalledWith(
                '42',
                'note1',
                expect.objectContaining({ version: 7 }),
                expect.anything()
            )
            const collision = await move(2, 'Published', 2, 'Research')
            expect(collision.type).toBe(7)
            expect(collision.body.number(4)).toBe(17)
            const cycle = await move(2, 'Published', 5, 'Nested')
            expect(cycle.type).toBe(7)
            expect(cycle.body.number(4)).toBe(22)
            const outside = await move(2, 'Published', 1, 'Outside')
            expect(outside.type).toBe(7)
            expect(outside.body.number(4)).toBe(30)
            expect(apiMutator).toHaveBeenCalledTimes(2)
            jest.mocked(apiMutator).mockRejectedValue(new Error('Permission denied'))
            expect((await move(5, 'Renamed.md', 3, 'Denied.md')).type).toBe(7)
            expect(fs.resolveReference('Published/Renamed.md', '/posthog/files', 'notebook')).toBe('note1')
            expect(() => fs.resolveReference('Research/Denied.md', '/posthog/files')).toThrow('No project file')
        }
    )

    it('loads every page and keeps legacy notebooks and duplicate names accessible', async () => {
        jest.mocked(fileSystemList)
            .mockResolvedValueOnce({ count: 3, next: '/next', results: [entry('note1', 'Research/Notes')] })
            .mockResolvedValueOnce({
                count: 3,
                next: null,
                results: [entry('note2', 'Research/Notes'), entry('legacy', 'Research/Legacy')],
            })
        jest.mocked(notebooksRetrieve).mockImplementation(async (_, id) =>
            id === 'legacy' ? { ...notebook, content: { type: 'doc', content: [{ type: 'paragraph' }] } } : notebook
        )
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        await fs.load()
        const directory = fs.root.children!.get('files')!.children!.get('Research')!
        expect([...directory.children!.keys()].sort()).toEqual(['Legacy.json', 'Notes.md', 'Notes~note2.md'])
        expect(directory.children!.get('Legacy.json')!.writable).toBe(true)
        const api = fs.root.children!.get('api')!.children!.get('notebook')!.children!.get('note1.json')!
        expect(JSON.parse(decoder.decode((await api.open!()).bytes)).version).toBe(7)
        expect(jest.mocked(fileSystemList).mock.calls[1][1]?.offset).toBe(1)
    })

    it('does not offer writes on viewer notebooks or expose entries without read access', async () => {
        jest.mocked(fileSystemList).mockResolvedValue({
            count: 2,
            results: [entry('note1', 'Notes'), { ...entry('hidden', 'Hidden'), user_access_level: 'none' }],
        })
        jest.mocked(notebooksList).mockResolvedValue({
            count: 1,
            results: [{ ...notebookIndex, user_access_level: 'viewer' }],
        })
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        await fs.load()
        const files = fs.root.children!.get('files')!
        expect([...files.children!.keys()]).toEqual(['Notes.md'])
        expect(files.children!.get('Notes.md')!.writable).toBe(false)
        expect(fs.root.children!.get('api')!.children!.get('notebook')!.children!.get('note1.json')!.writable).toBe(
            false
        )
    })

    it.each([
        ['dashboard', 'dashboards', '12'],
        ['insight', 'insights', 'insightId'],
        ['feature_flag', 'feature_flags', '13'],
        ['cohort', 'cohorts', '14'],
        ['action', 'actions', '15'],
        ['survey', 'surveys', '01900000-0000-7000-8000-000000000003'],
        ['experiment', 'experiments', '16'],
    ])('reads and saves %s JSON through its project-scoped endpoint from both mounts', async (type, route, ref) => {
        jest.mocked(fileSystemList).mockResolvedValue({ count: 1, results: [entry(ref, 'Object', type)] })
        const original = {
            id: ref,
            name: 'Original',
            nested: { enabled: false },
            readonly_field: 'from API',
            restriction_level: 0,
            ...(['experiment', 'feature_flag'].includes(type) ? { version: 7 } : {}),
        }
        jest.mocked(apiMutator).mockResolvedValue(original)
        const signal = new AbortController().signal
        const fs = new PosthogFilesystem('42', signal)
        await fs.load()
        expect(apiMutator).not.toHaveBeenCalled()
        const files = [
            fs.root.children!.get('files')!.children!.get('Object.json')!,
            fs.root.children!.get('api')!.children!.get(type)!.children!.get(`${ref}.json`)!,
        ]
        for (const file of files) {
            expect(file.writable).toBe(true)
            const opened = await file.open!()
            expect(JSON.parse(decoder.decode(opened.bytes))).toEqual(original)
            expect(apiMutator).toHaveBeenLastCalledWith(`/api/projects/42/${route}/${ref}/`, { method: 'GET', signal })
            const callsBeforeSave = jest.mocked(apiMutator).mock.calls.length
            await opened.save!(opened.bytes)
            expect(apiMutator).toHaveBeenCalledTimes(callsBeforeSave)
            const edited = { ...original, id: 'another-id', name: 'Edited', nested: { enabled: true } }
            await opened.save!(new TextEncoder().encode(JSON.stringify(edited)))
            expect(apiMutator).toHaveBeenLastCalledWith(`/api/projects/42/${route}/${ref}/`, {
                method: 'PATCH',
                signal,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    id: 'another-id',
                    name: 'Edited',
                    nested: { enabled: true },
                    ...(['experiment', 'feature_flag'].includes(type) ? { version: 7 } : {}),
                }),
            })
        }
    })

    it('rejects invalid JSON and propagates API failures without retrying a failed update', async () => {
        jest.mocked(fileSystemList).mockResolvedValue({ count: 1, results: [entry('12', 'Object', 'dashboard')] })
        jest.mocked(apiMutator).mockResolvedValue({ id: 12, name: 'Original' })
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        await fs.load()
        const file = await fs.root.children!.get('files')!.children!.get('Object.json')!.open!()
        jest.mocked(apiMutator).mockClear()
        for (const invalid of ['{', 'null', '[]', '"text"', '123']) {
            await expect(file.save!(new TextEncoder().encode(invalid))).rejects.toThrow(/JSON/)
        }
        expect(apiMutator).not.toHaveBeenCalled()
        const error = { status: 400, detail: 'Name cannot be empty.' }
        jest.mocked(apiMutator).mockRejectedValueOnce(error)
        await expect(file.save!(new TextEncoder().encode('{"name":""}'))).rejects.toBe(error)
        expect(apiMutator).toHaveBeenCalledTimes(1)
    })

    it('keeps unsupported objects and viewer JSON read-only', async () => {
        jest.mocked(fileSystemList).mockResolvedValue({
            count: 2,
            results: [
                entry('unsupported', 'Unknown', 'unknown'),
                { ...entry('12', 'View only', 'dashboard'), user_access_level: 'viewer' },
            ],
        })
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        await fs.load()
        for (const node of fs.root.children!.get('files')!.children!.values()) {
            expect(node.writable).toBe(false)
        }
        for (const directory of fs.root.children!.get('api')!.children!.values()) {
            expect([...directory.children!.values()][0].writable).toBe(false)
        }
    })

    it.each([
        ['notebook', 'invalid/id'],
        ['insight', 'invalid?query'],
        ['survey', 'invalid-id'],
        ['dashboard', 'not-a-number'],
        ['dashboard', '9007199254740993'],
    ])('keeps %s records with invalid object IDs read-only', async (type, ref) => {
        jest.mocked(fileSystemList).mockResolvedValue({
            count: 1,
            results: [{ ...entry('record', 'Object', type), ref }],
        })
        jest.mocked(fileSystemRetrieve).mockResolvedValue({ ...entry('record', 'Object', type), ref })
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        await fs.load()
        const nodes = [
            fs.root.children!.get('files')!.children!.get('Object.json')!,
            fs.root
                .children!.get('api')!
                .children!.get(type)!
                .children!.get(`${terminalFilename(ref)}.json`)!,
        ]
        for (const node of nodes) {
            expect(node.writable).toBe(false)
            expect((await node.open!()).save).toBeUndefined()
        }
        expect(fileSystemRetrieve).toHaveBeenCalledTimes(2)
        expect(fileSystemRetrieve).toHaveBeenLastCalledWith('42', 'record', expect.anything())
        expect(apiMutator).not.toHaveBeenCalled()
        expect(notebooksRetrieve).not.toHaveBeenCalled()
    })

    it('saves notebook JSON with the opened version and advances it after a successful save', async () => {
        const session = new AbortController()
        const read = new AbortController()
        const fs = new PosthogFilesystem('42', session.signal)
        await fs.load()
        const file = await fs.root.children!.get('api')!.children!.get('notebook')!.children!.get('note1.json')!.open!(
            read.signal
        )
        read.abort()
        expect(jest.mocked(notebooksRetrieve).mock.calls[0][2]?.signal).not.toBe(session.signal)
        jest.mocked(notebooksPartialUpdate).mockResolvedValue({ ...notebook, version: 8 })
        await file.save!(file.bytes)
        expect(notebooksPartialUpdate).not.toHaveBeenCalled()
        const data = new TextEncoder().encode(JSON.stringify({ ...notebook, title: 'Edited', version: 99 }))
        await file.save!(data)
        expect(notebooksPartialUpdate).toHaveBeenLastCalledWith(
            '42',
            'note1',
            expect.objectContaining({ title: 'Edited', version: 7 }),
            expect.objectContaining({ signal: session.signal })
        )
        await file.save!(data)
        expect(notebooksPartialUpdate).toHaveBeenLastCalledWith(
            '42',
            'note1',
            expect.objectContaining({ version: 8 }),
            expect.objectContaining({ signal: session.signal })
        )
    })

    it('keeps notebook search text synchronized when saving JSON content', async () => {
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        await fs.load()
        const file = await fs.root.children!.get('api')!.children!.get('notebook')!.children!.get('note1.json')!.open!()
        const content = {
            type: 'doc',
            content: [{ type: 'ph-markdown-notebook', attrs: { markdown: 'New search text' } }],
        }
        await file.save!(new TextEncoder().encode(JSON.stringify({ ...notebook, content })))
        expect(notebooksPartialUpdate).toHaveBeenLastCalledWith(
            '42',
            'note1',
            { content, text_content: 'New search text', version: 7 },
            expect.anything()
        )
    })

    it.each([
        ['..', '%2E%2E'],
        ['.', '%2E'],
        ['a/b', 'a%2Fb'],
        ['%2F', '%252F'],
        ['hello\nworld', 'hello%0Aworld'],
        ['csi\u009bm', 'csi%C2%9Bm'],
        ['osc\u009d0;x', 'osc%C2%9D0;x'],
        ['pad\u0080', 'pad%C2%80'],
        ['keeps\u00a0non-control', 'keeps\u00a0non-control'],
    ])('maps %j to a Unix filename without changing directory structure', (input, expected) => {
        expect(terminalFilename(input)).toBe(expected)
    })

    it('keeps long Unicode names addressable within Linux filename limits', () => {
        const first = terminalFilename('🦔'.repeat(100))
        const second = terminalFilename('🦔'.repeat(101))
        expect(new TextEncoder().encode(first).length).toBeLessThan(180)
        expect(first).not.toBe(second)
        expect(first).toBe(terminalFilename('🦔'.repeat(100)))
        expect(first).not.toContain('\uFFFD')
    })
})
