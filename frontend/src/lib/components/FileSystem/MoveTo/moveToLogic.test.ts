/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { moveToLogic } from 'lib/components/FileSystem/MoveTo/moveToLogic'

import { useMocks } from '~/mocks/jest'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

const entry = (id: string, path: string, extras: Partial<FileSystemEntry> = {}): FileSystemEntry =>
    ({ id, path, type: 'dashboard', ref: '1', ...extras }) as FileSystemEntry

describe('moveToLogic', () => {
    let logic: ReturnType<typeof moveToLogic.build>
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
        logic = moveToLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('looks a ref up in the file system and opens the modal with the entry it finds', async () => {
        mockFileSystem({ '1': [entry('fs-1', 'Marketing/Weekly numbers')] })

        await expectLogic(logic, () => {
            logic.actions.openMoveToModalForRefs([{ type: 'dashboard', ref: '1' }])
        })
            .toFinishAllListeners()
            .toMatchValues({
                isOpen: true,
                movingItems: [expect.objectContaining({ id: 'fs-1' })],
            })
        expect(listedRefs).toEqual(['1'])
    })

    // A shortcut shares its ref with the row it points at. Moving the shortcut leaves the dashboard where it
    // was, so the lookup has to skip past it.
    it('skips shortcut rows when picking the entry to move', async () => {
        mockFileSystem({
            '1': [
                entry('fs-shortcut', 'Shortcuts/Weekly numbers', { shortcut: true }),
                entry('fs-1', 'Weekly numbers'),
            ],
        })

        await expectLogic(logic, () => {
            logic.actions.openMoveToModalForRefs([{ type: 'dashboard', ref: '1' }])
        })
            .toFinishAllListeners()
            .toMatchValues({ movingItems: [expect.objectContaining({ id: 'fs-1' })] })
    })

    it('leaves the modal closed when nothing resolves', async () => {
        mockFileSystem({})

        await expectLogic(logic, () => {
            logic.actions.openMoveToModalForRefs([{ type: 'dashboard', ref: '1' }])
        })
            .toFinishAllListeners()
            .toMatchValues({ isOpen: false, movingItems: [] })
    })

    it('moves the refs that do resolve when only some of a selection is in the file system', async () => {
        mockFileSystem({ '2': [entry('fs-2', 'Marketing/Revenue', { ref: '2' })] })

        await expectLogic(logic, () => {
            logic.actions.openMoveToModalForRefs([
                { type: 'dashboard', ref: '1' },
                { type: 'dashboard', ref: '2' },
            ])
        })
            .toFinishAllListeners()
            .toMatchValues({ isOpen: true, movingItems: [expect.objectContaining({ id: 'fs-2' })] })
    })
})
