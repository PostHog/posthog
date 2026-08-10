/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { resolveProjectTreeRefs } from 'lib/components/FileSystem/resolveProjectTreeRefs'

import { useMocks } from '~/mocks/jest'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

const entry = (id: string, ref: string, extras: Partial<FileSystemEntry> = {}): FileSystemEntry =>
    ({ id, ref, path: `Marketing/${id}`, type: 'dashboard', ...extras }) as FileSystemEntry

describe('resolveProjectTreeRefs', () => {
    let listedRefs: string[]

    const mockFileSystem = (resultsByRef: Record<string, FileSystemEntry[]>): void => {
        useMocks({
            get: {
                '/api/environments/:team_id/file_system': ({ request }) => {
                    const ref = new URL(request.url).searchParams.get('ref') ?? ''
                    listedRefs.push(ref)
                    return [200, { count: 0, results: resultsByRef[ref] ?? [] }]
                },
            },
        })
    }

    beforeEach(() => {
        listedRefs = []
        initKeaTests()
    })

    it('returns the file system row for a ref', async () => {
        mockFileSystem({ '1': [entry('fs-1', '1')] })

        const entries = await resolveProjectTreeRefs([{ type: 'dashboard', ref: '1' }])

        expect(entries).toEqual([expect.objectContaining({ id: 'fs-1' })])
        expect(listedRefs).toEqual(['1'])
    })

    // A shortcut shares its ref with the row it points at. Moving the shortcut leaves the object where it
    // was, so the lookup has to skip past it.
    it('skips shortcut rows', async () => {
        mockFileSystem({ '1': [entry('fs-shortcut', '1', { shortcut: true }), entry('fs-1', '1')] })

        const entries = await resolveProjectTreeRefs([{ type: 'dashboard', ref: '1' }])

        expect(entries).toEqual([expect.objectContaining({ id: 'fs-1' })])
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

    // More refs than one batch, to prove nothing is dropped when the lookup chunks its requests.
    it('resolves every ref in a selection larger than one batch', async () => {
        const ids = Array.from({ length: 25 }, (_, index) => String(index))
        mockFileSystem(Object.fromEntries(ids.map((id) => [id, [entry(`fs-${id}`, id)]])))

        const entries = await resolveProjectTreeRefs(ids.map((ref) => ({ type: 'dashboard', ref })))

        expect(entries).toHaveLength(25)
        expect(listedRefs.sort()).toEqual(ids.sort())
    })
})
