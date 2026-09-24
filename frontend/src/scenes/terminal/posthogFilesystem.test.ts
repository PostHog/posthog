import { waitFor } from '@testing-library/react'

import apiMutator from 'lib/api-orval-mutator'

import { fileSystemCreate, fileSystemDestroy, fileSystemList, fileSystemRetrieve } from '~/generated/core/api'
import type { FileSystemApi } from '~/generated/core/api.schemas'

import { notebooksList, notebooksPartialUpdate, notebooksRetrieve } from 'products/notebooks/frontend/generated/api'
import type { NotebookApi } from 'products/notebooks/frontend/generated/api.schemas'
import { insightsList } from 'products/product_analytics/frontend/generated/api'

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

jest.mock('products/product_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/product_analytics/frontend/generated/api'),
    insightsList: jest.fn(),
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
        meta: type === 'notebook' ? { content_type: 'text/markdown' } : {},
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
    beforeEach(() => {
        jest.clearAllMocks()
        jest.mocked(insightsList).mockResolvedValue({ count: 0, results: [] })
        jest.mocked(fileSystemList).mockResolvedValue({
            count: 1,
            next: null,
            results: [entry('note1', 'Research/Notes')],
        })
        jest.mocked(notebooksRetrieve).mockResolvedValue(notebook)
    })

    it('edits SQL while preserving insight options and exposes editable JSON metadata', async () => {
        const signal = new AbortController().signal
        jest.mocked(fileSystemList).mockResolvedValue({
            count: 1,
            results: [{ ...entry('sql1', 'Research/Report', 'insight'), meta: { content_type: 'application/sql' } }],
        })
        const original = {
            name: 'Report',
            query: { kind: 'DataTableNode', source: { kind: 'HogQLQuery', query: 'select 1', limit: 10 }, full: true },
        }
        jest.mocked(apiMutator).mockResolvedValue(original)
        const fs = new PosthogFilesystem('42', signal)
        await fs.load()
        expect(insightsList).not.toHaveBeenCalled()
        expect(apiMutator).not.toHaveBeenCalled()
        const sql =
            await fs.root.children!.get('files')!.children!.get('Research')!.children!.get('Report.sql')!.open!()
        expect(decoder.decode(sql.bytes)).toBe('select 1')
        await sql.save!(new TextEncoder().encode('select 2'))
        expect(apiMutator).toHaveBeenLastCalledWith(
            '/api/projects/42/insights/sql1/',
            expect.objectContaining({
                method: 'PATCH',
                body: JSON.stringify({
                    query: { ...original.query, source: { ...original.query.source, query: 'select 2' } },
                }),
            })
        )
        expect(await fs.queryFor('/posthog/files/Research/Report.sql', 'select 3')).toMatchObject({
            query: 'select 3',
            limit: 10,
        })
        const json = fs.root.children!.get('api')!.children!.get('insight')!.children!.get('sql1.json')!
        expect(json.writable).toBe(true)
        const opened = await json.open!()
        await opened.save!(new TextEncoder().encode(JSON.stringify({ ...original, name: 'Renamed' })))
        expect(apiMutator).toHaveBeenLastCalledWith(
            '/api/projects/42/insights/sql1/',
            expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ name: 'Renamed' }) })
        )
    })

    it('resolves unvisited object folders without loading the project tree', async () => {
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        expect(await fs.folderFor({ type: 'notebook', ref: 'note1' })).toBe('/posthog/files/Research')
        expect(fileSystemList).toHaveBeenCalledWith(
            '42',
            { type: 'notebook', ref: 'note1', limit: 1 },
            expect.anything()
        )
        jest.mocked(fileSystemList).mockClear()
        expect(await fs.folderFor({ type: 'folder', ref: "Research/A's notes" })).toBe(
            "/posthog/files/Research/A's notes"
        )
        expect(fileSystemList).not.toHaveBeenCalled()
    })

    it('loads only browsed folders, shares pending requests, and refreshes visited directories', async () => {
        let entries = [
            entry('research', 'Research', 'folder'),
            entry('other', 'Other', 'folder'),
            entry('nested', 'Research/Nested', 'folder'),
            entry('note1', 'Research/Notes'),
            entry('12', 'Other/Dashboard', 'dashboard'),
            { ...entry('sql1', 'Research/Query', 'insight'), meta: { content_type: 'application/sql' } },
            entry('trend1', 'Research/Trend', 'insight'),
        ]
        jest.mocked(fileSystemList).mockImplementation(async (_, params) => {
            const { parent, depth, type } = params as { parent?: string; depth?: number; type?: string }
            const results = entries.filter((item) =>
                type
                    ? item.type === type
                    : item.path.split('/').length === depth && item.path.split('/').slice(0, -1).join('/') === parent
            )
            return { count: results.length, results }
        })
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        const server = new NinePServer(fs, jest.fn())
        const request = async (type: number, body: NinePWriter): Promise<NinePReader> => {
            const bytes = await new Promise<Uint8Array>((resolve) => server.handle(body.frame(type, 1), resolve))
            const response = new NinePReader(bytes)
            response.number(4)
            expect(response.number(1)).toBe(type + 1)
            response.number(2)
            return response
        }
        await request(104, new NinePWriter().number(1, 4).number(0xffffffff, 4).string('root').string(''))
        await request(110, new NinePWriter().number(1, 4).number(2, 4).number(1, 2).string('files'))
        expect(fileSystemList).not.toHaveBeenCalled()
        await request(40, new NinePWriter().number(2, 4).number(0, 8).number(4096, 4))
        expect(fileSystemList).toHaveBeenCalledTimes(1)
        expect(fileSystemList).toHaveBeenLastCalledWith(
            '42',
            { parent: '', depth: 1, include_content_type: true, limit: 500, offset: 0 },
            expect.anything()
        )
        expect(notebooksList).not.toHaveBeenCalled()
        const files = fs.root.children!.get('files')!
        const research = files.children!.get('Research')!
        expect(research.children!.size).toBe(0)
        await Promise.all([research.loadChildren!(), research.loadChildren!()])
        expect(fileSystemList).toHaveBeenCalledTimes(2)
        expect(fileSystemList).toHaveBeenLastCalledWith(
            '42',
            { parent: 'Research', depth: 2, include_content_type: true, limit: 500, offset: 0 },
            expect.anything()
        )
        expect([...research.children!.keys()]).toEqual(['Nested', 'Notes.md', 'Query.sql', 'Trend.json'])
        expect(notebooksRetrieve).not.toHaveBeenCalled()
        const note = research.children!.get('Notes.md')!
        await request(
            110,
            new NinePWriter().number(2, 4).number(3, 4).number(2, 2).string('Research').string('Notes.md')
        )
        expect(fileSystemList).toHaveBeenCalledTimes(2)
        jest.mocked(fileSystemList).mockResolvedValueOnce({ count: 1, results: [entries[4]] })
        const cachedPath = jest.spyOn(
            Object.defineProperty(entries[3], 'path', { configurable: true, get: () => 'Research/Notes' }),
            'path',
            'get'
        )
        await files.children!.get('Other')!.loadChildren!()
        expect(files.children!.get('Other')!.children!.has('Dashboard.json')).toBe(true)
        expect(cachedPath).not.toHaveBeenCalled()
        cachedPath.mockRestore()
        entries.push(entry('note2', 'Research/New'))
        await fs.load()
        expect(fileSystemList).toHaveBeenCalledTimes(6)
        expect(research.children!.get('Notes.md')).toBe(note)
        expect(research.children!.has('New.md')).toBe(true)
        expect(files.children!.get('Other')!.children!.has('Dashboard.json')).toBe(true)
        expect(research.children!.get('Nested')!.children!.size).toBe(0)
        expect(insightsList).not.toHaveBeenCalled()
        expect(notebooksList).not.toHaveBeenCalled()
        expect(apiMutator).not.toHaveBeenCalled()
        expect(notebooksRetrieve).not.toHaveBeenCalled()
        entries = entries.map((item) => ({ ...item, path: item.path.replace(/^Research/, 'Published') }))
        await fs.load()
        expect(files.children!.has('Research')).toBe(false)
        expect(files.children!.has('Published')).toBe(true)
        await fs.loadReference('/posthog/files/Published/Notes.md', '/')
        expect(fs.resolveReference('/posthog/files/Published/Notes.md', '/')).toBe('note1')
        const publishedNote = files.children!.get('Published')!.children!.get('Notes.md')!
        entries = entries.filter((item) => !item.path.startsWith('Published'))
        await fs.load()
        expect(files.children!.has('Published')).toBe(false)
        await expect(publishedNote.open!()).rejects.toMatchObject({ errno: 116 })
    })

    it.each(['dashboard', 'hog_function/source', 'unknown'])(
        'loads API paths for %s and retries failed directory pages without caching partial results',
        async (type) => {
            const fs = new PosthogFilesystem('42', new AbortController().signal)
            const server = new NinePServer(fs, jest.fn())
            const request = async (type: number, body: NinePWriter): Promise<NinePReader> => {
                const bytes = await new Promise<Uint8Array>((resolve) => server.handle(body.frame(type, 1), resolve))
                const response = new NinePReader(bytes)
                response.number(4)
                expect(response.number(1)).toBe(type + 1)
                response.number(2)
                return response
            }
            await request(104, new NinePWriter().number(1, 4).number(0xffffffff, 4).string('root').string(''))
            const name = encodeURIComponent(type)
            const walked = await request(
                110,
                new NinePWriter().number(1, 4).number(2, 4).number(2, 2).string('api').string(name)
            )
            expect(walked.number(2)).toBe(2)
            const directory = fs.root.children!.get('api')!.children!.get(name)!
            expect(fileSystemList).not.toHaveBeenCalled()
            jest.mocked(fileSystemList)
                .mockResolvedValueOnce({ count: 2, next: '/next', results: [entry('12', 'First', type)] })
                .mockRejectedValueOnce(new Error('Try again'))
            await expect(directory.loadChildren!()).rejects.toThrow('Try again')
            expect(directory.children!.size).toBe(0)
            jest.mocked(fileSystemList)
                .mockResolvedValueOnce({ count: 2, next: '/next', results: [entry('12', 'First', type)] })
                .mockResolvedValueOnce({ count: 2, next: null, results: [entry('13', 'Second', type)] })
            await fs.loadReference(`/posthog/api/${name}/13.json`, '/')
            expect(fs.resolveReference(`/posthog/api/${name}/13.json`, '/', type)).toBe('13')
            expect([...directory.children!.keys()]).toEqual(['12.json', '13.json'])
            expect(jest.mocked(fileSystemList).mock.calls.map(([, params]) => params)).toEqual([
                { type, include_content_type: true, limit: 500, offset: 0 },
                { type, include_content_type: true, limit: 500, offset: 1 },
                { type, include_content_type: true, limit: 500, offset: 0 },
                { type, include_content_type: true, limit: 500, offset: 1 },
            ])
            expect(notebooksList).not.toHaveBeenCalled()
            expect(apiMutator).not.toHaveBeenCalled()
            jest.mocked(fileSystemList).mockResolvedValue({ count: 0, next: null, results: [] })
            await fs.load()
            expect(fs.root.children!.get('api')!.children!.get(name)).toBe(directory)
            expect(directory.children!.size).toBe(0)
            const fresh = new PosthogFilesystem('42', new AbortController().signal)
            jest.mocked(fileSystemList).mockResolvedValue({ count: 1, results: [entry('13', 'Second', type)] })
            await fresh.loadReference(`/posthog/api/${name}/13.json`, '/')
            expect(fresh.resolveReference(`/posthog/api/${name}/13.json`, '/', type)).toBe('13')
        }
    )

    it('resolves navigation from lazy folders and file identities without reading their contents', async () => {
        const folder = 'Research & notes'
        const entries = [
            entry('folder', folder, 'folder'),
            entry('note1', `${folder}/Notes`),
            { ...entry('query', `${folder}/Query.sql`, 'insight'), href: '/insights/query' },
            entry('12', `${folder}/Overview`, 'dashboard'),
        ]
        jest.mocked(fileSystemList).mockImplementation(async (_, params) => {
            const { parent, depth } = params as { parent?: string; depth?: number }
            const results = entries.filter(
                (item) =>
                    item.path.split('/').length === depth && item.path.split('/').slice(0, -1).join('/') === parent
            )
            return { count: results.length, results }
        })
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        expect(await fs.navigationUrl(folder, '/posthog/files')).toBe('/files?folder=Research%20%26%20notes')
        expect(fileSystemList).toHaveBeenCalledTimes(1)
        expect(await fs.navigationUrl('Notes.md', `/posthog/files/${folder}`)).toBe('/notebooks/note1')
        expect(await fs.navigationUrl('Query.sql.json', `/posthog/files/${folder}`)).toBe('/insights/query')
        expect(await fs.navigationUrl('Overview.json', `/posthog/files/${folder}`)).toBe('/dashboard/12')
        expect(notebooksRetrieve).not.toHaveBeenCalled()
        expect(fileSystemRetrieve).not.toHaveBeenCalled()
    })

    it.each(['https://example.com', '//example.com', '/\\example.com', 'javascript:alert(1)', '/\n/example.com'])(
        'rejects a file destination outside PostHog: %j',
        async (href) => {
            jest.mocked(fileSystemList).mockResolvedValue({
                count: 1,
                results: [{ ...entry('link', 'Link', 'unknown'), href }],
            })
            const fs = new PosthogFilesystem('42', new AbortController().signal)
            await expect(fs.navigationUrl('Link.json', '/posthog/files')).rejects.toThrow('no PostHog page')
        }
    )

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
        expect(notebooksList).not.toHaveBeenCalled()
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
        const fs = new PosthogFilesystem('42', new AbortController().signal, async () => true)
        await fs.load()
        const files = fs.root.children!.get('files')!
        const folder = files.children!.get('Research')!
        const note = folder.children!.get('Notes.md')!
        await expect(folder.remove!()).rejects.toMatchObject({ errno: 39 })
        expect(fileSystemDestroy).not.toHaveBeenCalled()
        jest.mocked(fileSystemDestroy).mockRejectedValueOnce(
            Object.assign(new Error('You do not have permission to delete this file.'), { status: 403 })
        )
        await expect(note.remove!()).rejects.toMatchObject({
            errno: 13,
            message:
                'Could not delete /posthog/files/Research/Notes.md (HTTP 403):\nYou do not have permission to delete this file.\nRun ph refresh to check the remaining files before trying again.',
        })
        expect(fs.resolveReference('Research/Notes.md', '/posthog/files')).toBe('note1')
        jest.mocked(fileSystemDestroy).mockRejectedValueOnce({ status: 500 })
        await expect(note.remove!()).rejects.toMatchObject({
            errno: 5,
            message: expect.stringContaining('Could not delete /posthog/files/Research/Notes.md (HTTP 500)'),
        })
        expect(folder.children!.get('Notes.md')).toBe(note)
        jest.mocked(fileSystemDestroy).mockRejectedValueOnce(new TypeError('Failed to fetch'))
        await expect(note.remove!()).rejects.toMatchObject({
            errno: 5,
            message: expect.stringContaining('Could not delete /posthog/files/Research/Notes.md:\nFailed to fetch'),
        })
        expect(folder.children!.get('Notes.md')).toBe(note)
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

    it.each([false, true])(
        'confirms a recursive snapshot once before any API deletion (approved=%s)',
        async (approved) => {
            const entries = [
                entry('folder', 'Research', 'folder'),
                entry('note1', 'Research/Notes'),
                entry('note2', 'Research/More'),
            ]
            jest.mocked(fileSystemList).mockImplementation(async (_, params) => {
                const { parent, depth } = params as { parent?: string; depth?: number }
                const results = entries.filter(
                    (item) =>
                        item.path.split('/').length === depth && item.path.split('/').slice(0, -1).join('/') === parent
                )
                return { count: results.length, results }
            })
            let answer!: (approved: boolean) => void
            const confirm = jest.fn(
                () =>
                    new Promise<boolean>((resolve) => {
                        answer = resolve
                    })
            )
            const fs = new PosthogFilesystem('42', new AbortController().signal, confirm)
            const operation = fs.removePaths(['/posthog/files/Research'], true, true)
            const outcome = operation.catch((error: Error) => error)
            await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
            expect(confirm.mock.calls[0]).toEqual([
                expect.objectContaining({
                    items: [
                        '/posthog/files/Research/More.md (notebook: note2)',
                        '/posthog/files/Research/Notes.md (notebook: note1)',
                        '/posthog/files/Research',
                    ],
                }),
            ])
            expect(fileSystemDestroy).not.toHaveBeenCalled()
            answer(approved)
            if (approved) {
                await expect(outcome).resolves.toBeUndefined()
                expect(jest.mocked(fileSystemDestroy).mock.calls.map((call) => call[1])).toEqual([
                    'note2',
                    'note1',
                    'folder',
                ])
            } else {
                await expect(outcome).resolves.toEqual(
                    expect.objectContaining({ message: 'Canceled. No changes made.' })
                )
                expect(fileSystemDestroy).not.toHaveBeenCalled()
            }
            expect(confirm).toHaveBeenCalledTimes(1)
            expect(notebooksRetrieve).not.toHaveBeenCalled()
        }
    )

    it.each(['remove', 'json', 'edit-json', 'markdown', 'mkdir', 'rename'] as const)(
        'fails closed without a confirmation handler for %s',
        async (operation) => {
            const fs = new PosthogFilesystem('42', new AbortController().signal, undefined, true)
            await fs.load()
            const files = fs.root.children!.get('files')!
            const node = ['remove', 'markdown', 'rename'].includes(operation)
                ? files.children!.get('Research')!.children!.get('Notes.md')!
                : fs.root.children!.get('api')!.children!.get('notebook')!.children!.get('note1.json')!
            const pending =
                operation === 'remove'
                    ? node.remove!()
                    : operation === 'mkdir'
                      ? files.mkdir!('New folder')
                      : operation === 'rename'
                        ? node.rename!(files, 'Renamed.md')
                        : (await node.open!()).save!(
                              new TextEncoder().encode(
                                  operation === 'markdown'
                                      ? '# Changed'
                                      : JSON.stringify(operation === 'json' ? { deleted: true } : { title: 'Changed' })
                              )
                          )
            await expect(pending).rejects.toThrow('Canceled. No changes made.')
            expect(fileSystemDestroy).not.toHaveBeenCalled()
            expect(fileSystemCreate).not.toHaveBeenCalled()
            expect(apiMutator).not.toHaveBeenCalled()
            expect(notebooksPartialUpdate).not.toHaveBeenCalled()
        }
    )

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
                results: [
                    entry('note2', 'Research/Notes'),
                    { ...entry('legacy', 'Research/Legacy'), meta: { content_type: 'application/json' } },
                ],
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
            results: [
                { ...entry('note1', 'Notes'), user_access_level: 'viewer' },
                { ...entry('hidden', 'Hidden'), user_access_level: 'none' },
            ],
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

    it('updates permissions in both projections when browsing an overlapping API type', async () => {
        const object = entry('12', 'Object', 'dashboard')
        jest.mocked(fileSystemList).mockResolvedValue({ count: 1, results: [object] })
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        await fs.root.children!.get('files')!.loadChildren!()
        const file = fs.root.children!.get('files')!.children!.get('Object.json')!
        const type = fs.root.children!.get('api')!.children!.get('dashboard')!
        const apiFile = type.children!.get('12.json')!
        expect(file.writable).toBe(true)
        expect(apiFile.writable).toBe(true)
        jest.mocked(fileSystemList).mockResolvedValue({
            count: 1,
            results: [{ ...object, user_access_level: 'viewer' }],
        })
        await type.loadChildren!()
        expect(file.writable).toBe(false)
        expect(apiFile.writable).toBe(false)
        expect(fs.root.children!.get('files')!.children!.get('Object.json')).toBe(file)
        expect(type.children!.get('12.json')).toBe(apiFile)
    })

    it('renames a file when its content type changes while browsing an overlapping API type', async () => {
        const note = entry('note1', 'Notes')
        jest.mocked(fileSystemList).mockResolvedValue({ count: 1, results: [note] })
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        const files = fs.root.children!.get('files')!
        await files.loadChildren!()
        const markdown = files.children!.get('Notes.md')!
        jest.mocked(fileSystemList).mockResolvedValue({
            count: 1,
            results: [{ ...note, meta: { content_type: 'application/json' } }],
        })
        await fs.root.children!.get('api')!.children!.get('notebook')!.loadChildren!()
        expect([...files.children!.keys()]).toEqual(['Notes.json'])
        await expect(markdown.open!()).rejects.toMatchObject({ errno: 116 })
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
        for (const type of ['unknown', 'dashboard']) {
            const directory = fs.root.children!.get('api')!.children!.get(type)!
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
