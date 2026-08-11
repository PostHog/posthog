/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { resolveProjectTreeRefs } from 'lib/components/FileSystem/resolveProjectTreeRefs'

import { useMocks } from '~/mocks/jest'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

const entry = (id: string, ref: string, extras: Partial<FileSystemEntry> = {}): FileSystemEntry =>
    ({ id, ref, path: `Marketing/${id}`, type: 'dashboard', ...extras }) as FileSystemEntry

describe('resolveProjectTreeRefs', () => {
    let listedRefs: string[]
    let listedTypeParams: Record<string, string | null>[]
    let requestCount: number

    const mockFileSystem = (resultsByRef: Record<string, FileSystemEntry[]>): void => {
        useMocks({
            get: {
                '/api/environments/:team_id/file_system': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const refs = params.getAll('ref')
                    listedRefs.push(...refs)
                    requestCount += 1
                    listedTypeParams.push({
                        type: params.get('type'),
                        type__startswith: params.get('type__startswith'),
                    })
                    return [200, { count: 0, results: refs.flatMap((ref) => resultsByRef[ref] ?? []) }]
                },
            },
        })
    }

    beforeEach(() => {
        listedRefs = []
        listedTypeParams = []
        requestCount = 0
        initKeaTests()
    })

    it('returns the file system row for a ref', async () => {
        mockFileSystem({ '1': [entry('fs-1', '1')] })

        const entries = await resolveProjectTreeRefs([{ type: 'dashboard', ref: '1' }])

        expect(entries).toEqual([expect.objectContaining({ id: 'fs-1' })])
        expect(listedRefs).toEqual(['1'])
    })

    it('skips shortcut rows', async () => {
        mockFileSystem({ '1': [entry('fs-shortcut', '1', { shortcut: true }), entry('fs-1', '1')] })

        const entries = await resolveProjectTreeRefs([{ type: 'dashboard', ref: '1' }])

        expect(entries).toEqual([expect.objectContaining({ id: 'fs-1' })])
    })

    it('matches on a type prefix when the ref carries one', async () => {
        mockFileSystem({ '1': [entry('fs-1', '1', { type: 'hog/site_destination' })] })

        const entries = await resolveProjectTreeRefs([{ type: 'hog/', ref: '1' }])

        expect(entries).toEqual([expect.objectContaining({ id: 'fs-1' })])
        expect(listedTypeParams).toEqual([{ type: null, type__startswith: 'hog/' }])
    })

    it('drops refs that have no row, keeping the ones that do', async () => {
        mockFileSystem({ '2': [entry('fs-2', '2')] })

        const entries = await resolveProjectTreeRefs([
            { type: 'dashboard', ref: '1' },
            { type: 'dashboard', ref: '2' },
            { type: 'dashboard', ref: null },
        ])

        expect(entries).toEqual([expect.objectContaining({ id: 'fs-2' })])
        // A null ref points at no object, so it never reaches the API.
        expect(listedRefs).toEqual(['1', '2'])
    })

    it('drops a batch whose request fails, keeping the batches that succeed', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/file_system': ({ request }) => {
                    const refs = new URL(request.url).searchParams.getAll('ref')
                    if (refs.includes('0')) {
                        return [500, { detail: 'boom' }]
                    }
                    return [200, { count: 0, results: refs.map((ref) => entry(`fs-${ref}`, ref)) }]
                },
            },
        })

        const ids = Array.from({ length: 60 }, (_, index) => String(index))
        const entries = await resolveProjectTreeRefs(ids.map((ref) => ({ type: 'dashboard', ref })))

        // The first batch of 50 carries ref '0' and fails; the remaining 10 still resolve.
        expect(entries.map((e) => e.id)).toEqual(ids.slice(50).map((ref) => `fs-${ref}`))
    })

    it('asks once for a whole selection instead of once per ref', async () => {
        mockFileSystem({ '1': [entry('fs-1', '1')], '2': [entry('fs-2', '2')], '3': [entry('fs-3', '3')] })

        const entries = await resolveProjectTreeRefs(['1', '2', '3'].map((ref) => ({ type: 'dashboard', ref })))

        expect(entries.map((e) => e.id)).toEqual(['fs-1', 'fs-2', 'fs-3'])
        expect(requestCount).toEqual(1)
        expect(listedRefs).toEqual(['1', '2', '3'])
    })

    it('resolves every ref in a selection larger than one batch', async () => {
        const ids = Array.from({ length: 120 }, (_, index) => String(index))
        mockFileSystem(Object.fromEntries(ids.map((id) => [id, [entry(`fs-${id}`, id)]])))

        const entries = await resolveProjectTreeRefs(ids.map((ref) => ({ type: 'dashboard', ref })))

        expect(entries).toHaveLength(120)
        expect(requestCount).toEqual(3)
        expect(listedRefs.sort()).toEqual(ids.sort())
    })
})
