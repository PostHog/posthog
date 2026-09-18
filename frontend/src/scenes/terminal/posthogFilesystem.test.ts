import { fileSystemList } from '~/generated/core/api'
import type { FileSystemApi } from '~/generated/core/api.schemas'

import { notebooksList, notebooksPartialUpdate, notebooksRetrieve } from 'products/notebooks/frontend/generated/api'
import type { NotebookApi, NotebookMinimalApi } from 'products/notebooks/frontend/generated/api.schemas'

import { PosthogFilesystem, terminalFilename } from './posthogFilesystem'

jest.mock('~/generated/core/api', () => ({ fileSystemList: jest.fn() }))
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
        short_id: 'note-1',
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
            results: [entry('note-1', 'Research/Notes')],
        })
        jest.mocked(notebooksList).mockResolvedValue({
            count: 2,
            next: null,
            results: [notebookIndex, { ...notebookIndex, short_id: 'note-2' }],
        })
        jest.mocked(notebooksRetrieve).mockResolvedValue(notebook)
    })

    it('projects markdown without changing the stored path and saves with the version it read', async () => {
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        await fs.load()
        expect(fs.resolveReference('./Notes.md', '/posthog/files/Research', 'notebook')).toBe('note-1')
        expect(fs.resolveReference('/posthog/api/notebook/note-1.json', '/', 'notebook')).toBe('note-1')
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
        const opened = await file.open!()
        expect(decoder.decode(opened.bytes)).toBe('# Hello 🦔')
        jest.mocked(notebooksPartialUpdate).mockResolvedValue({ ...notebook, version: 8 })
        await opened.save!(new TextEncoder().encode('# Updated'))
        expect(notebooksPartialUpdate).toHaveBeenCalledWith(
            '42',
            'note-1',
            {
                content: {
                    type: 'doc',
                    content: [{ type: 'ph-markdown-notebook', attrs: { markdown: '# Updated', nodeId: 'preserved' } }],
                },
                text_content: '# Updated',
                version: 7,
            },
            expect.objectContaining({ signal: expect.any(AbortSignal) })
        )
        jest.mocked(notebooksPartialUpdate).mockRejectedValue(new Error('Version conflict'))
        await expect(opened.save!(new TextEncoder().encode('Conflict'))).rejects.toThrow('Version conflict')
        expect(jest.mocked(notebooksPartialUpdate).mock.calls[1][2]?.version).toBe(8)
    })

    it('refreshes paths without fetching bodies or keeping deleted files addressable', async () => {
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        await fs.load()
        const oldId = fs.root.children!.get('files')!.children!.get('Research')!.children!.get('Notes.md')!.id
        jest.mocked(fileSystemList).mockResolvedValue({ count: 1, next: null, results: [entry('note-1', 'Renamed')] })
        await fs.load()
        const renamed = fs.root.children!.get('files')!.children!.get('Renamed.md')!
        expect(renamed.id).toBeGreaterThan(oldId)
        expect(fs.resolveReference('Renamed.md', '/posthog/files', 'notebook')).toBe('note-1')
        expect(() => fs.resolveReference('Research/Notes.md', '/posthog/files', 'notebook')).toThrow('No project file')
        expect(notebooksRetrieve).not.toHaveBeenCalled()
    })

    it('loads every page and keeps legacy notebooks and duplicate names accessible', async () => {
        jest.mocked(fileSystemList)
            .mockResolvedValueOnce({ count: 3, next: '/next', results: [entry('note-1', 'Research/Notes')] })
            .mockResolvedValueOnce({
                count: 3,
                next: null,
                results: [entry('note-2', 'Research/Notes'), entry('legacy', 'Research/Legacy')],
            })
        jest.mocked(notebooksRetrieve).mockImplementation(async (_, id) =>
            id === 'legacy' ? { ...notebook, content: { type: 'doc', content: [{ type: 'paragraph' }] } } : notebook
        )
        const fs = new PosthogFilesystem('42', new AbortController().signal)
        await fs.load()
        const directory = fs.root.children!.get('files')!.children!.get('Research')!
        expect([...directory.children!.keys()].sort()).toEqual(['Legacy.json', 'Notes.md', 'Notes~note-2.md'])
        expect(directory.children!.get('Legacy.json')!.writable).toBe(false)
        const api = fs.root.children!.get('api')!.children!.get('notebook')!.children!.get('note-1.json')!
        expect(JSON.parse(decoder.decode((await api.open!()).bytes)).version).toBe(7)
        expect(jest.mocked(fileSystemList).mock.calls[1][1]?.offset).toBe(1)
    })

    it('does not offer writes on viewer notebooks or expose entries without read access', async () => {
        jest.mocked(fileSystemList).mockResolvedValue({
            count: 2,
            results: [entry('note-1', 'Notes'), { ...entry('hidden', 'Hidden'), user_access_level: 'none' }],
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
    })

    it.each([
        ['..', '%2E%2E'],
        ['.', '%2E'],
        ['a/b', 'a%2Fb'],
        ['%2F', '%252F'],
        ['hello\nworld', 'hello%0Aworld'],
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
