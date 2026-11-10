import { accountsNotebooksPartialUpdate } from '../../generated/api'
import type { AccountNotebookApi } from '../../generated/api.schemas'
import { updateAccountNoteTags } from './accountNoteTagUpdates'

jest.mock('../../generated/api', () => ({ accountsNotebooksPartialUpdate: jest.fn() }))

const mockUpdate = jest.mocked(accountsNotebooksPartialUpdate)

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: Error) => void } {
    let resolve!: (value: T) => void
    let reject!: (error: Error) => void
    const promise = new Promise<T>((accept, refuse) => {
        resolve = accept
        reject = refuse
    })
    return { promise, resolve, reject }
}

const note = { short_id: 'review-note', tags: ['risk'] } as AccountNotebookApi

describe('account note tag updates', () => {
    beforeEach(() => mockUpdate.mockReset())

    it.each([false, true])('queues edits to one note even when the preceding write fails=%s', async (fails) => {
        const first = deferred<AccountNotebookApi>()
        const started = deferred<void>()
        mockUpdate.mockImplementationOnce(() => {
            started.resolve()
            return first.promise
        })
        mockUpdate.mockResolvedValueOnce(note)
        const firstWrite = updateAccountNoteTags('1', 'account-1', note.short_id, { tags: ['first'] })
        const firstResult = firstWrite.catch(() => undefined)
        await started.promise
        const latestWrite = updateAccountNoteTags('1', 'account-1', note.short_id, { tags: ['first', 'risk'] })
        expect(mockUpdate).toHaveBeenCalledTimes(1)

        if (fails) {
            first.reject(new Error('Save failed'))
        } else {
            first.resolve(note)
        }
        await firstResult
        await expect(latestWrite).resolves.toEqual(note)
        expect(mockUpdate).toHaveBeenLastCalledWith('1', 'account-1', note.short_id, { tags: ['first', 'risk'] })
    })

    it('does not block a different note behind a pending write', async () => {
        const pending = deferred<AccountNotebookApi>()
        const started = deferred<void>()
        mockUpdate.mockImplementationOnce(() => {
            started.resolve()
            return pending.promise
        })
        mockUpdate.mockResolvedValueOnce(note)
        const first = updateAccountNoteTags('1', 'account-1', 'note-1', { tags: ['risk'] })
        await started.promise
        await expect(updateAccountNoteTags('1', 'account-1', 'note-2', { tags: ['call'] })).resolves.toEqual(note)
        pending.resolve(note)
        await first
    })
})
