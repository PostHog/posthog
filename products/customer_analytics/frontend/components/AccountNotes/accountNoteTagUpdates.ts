import { accountsNotebooksPartialUpdate } from '../../generated/api'
import type { AccountNotebookApi, PatchedAccountNotebookUpdateApi } from '../../generated/api.schemas'

const noteWrites = new Map<string, Promise<AccountNotebookApi>>()

export async function updateAccountNoteTags(
    projectId: string,
    accountId: string,
    shortId: string,
    updates: PatchedAccountNotebookUpdateApi
): Promise<AccountNotebookApi> {
    const key = `${projectId}:${accountId}:${shortId}`
    const previous = noteWrites.get(key)
    const write = (previous ?? Promise.resolve())
        .catch(() => undefined)
        .then(() => accountsNotebooksPartialUpdate(projectId, accountId, shortId, updates))
    noteWrites.set(key, write)
    try {
        return await write
    } finally {
        if (noteWrites.get(key) === write) {
            noteWrites.delete(key)
        }
    }
}
