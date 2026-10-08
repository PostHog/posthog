import { toast } from '@posthog/quill'

import { tasksPartialUpdate, tasksPinCreate, tasksRunsCancelCreate } from 'products/tasks/frontend/generated/api'

import { TodayBulkVerb, bulkResultToast } from './todaySessionSelection'
import { TodayWorkItem, activeCloudRunId } from './todayWorkItems'

/** One request per session, like Desktop, since there is no bulk endpoint. Returns the ids that failed. */
async function runEach(ids: string[], request: (id: string) => Promise<unknown>): Promise<string[]> {
    const results = await Promise.allSettled(ids.map(request))
    return ids.filter((_, index) => results[index].status === 'rejected')
}

export function reportBulkResult(verb: TodayBulkVerb, total: number, failed: number, onUndo?: () => void): void {
    const result = bulkResultToast(verb, total - failed, failed)
    const action = onUndo && total > failed ? { label: 'Undo', onClick: onUndo } : undefined
    if (result.kind === 'success') {
        toast.success({ title: result.title, action })
    } else {
        toast.error({ title: result.title, description: result.description, action })
    }
}

export function pinSessions(teamId: string, ids: string[], pinned: boolean): Promise<string[]> {
    return runEach(ids, (id) => tasksPinCreate(teamId, id, { pinned }))
}

export function fileSessions(teamId: string, ids: string[], spaceId: string): Promise<string[]> {
    return runEach(ids, (id) => tasksPartialUpdate(teamId, id, { channel: spaceId }))
}

export function archiveSessions(teamId: string, sessions: TodayWorkItem[]): Promise<string[]> {
    const runIds = new Map(sessions.map((item) => [item.id, activeCloudRunId(item)]))
    return runEach([...runIds.keys()], async (id) => {
        const runId = runIds.get(id)
        // Archiving alone leaves the cloud run going, so stop it first, as the confirm says.
        if (runId) {
            await tasksRunsCancelCreate(teamId, id, runId)
        }
        await tasksPartialUpdate(teamId, id, { archived: true })
    })
}

export function restoreSessions(teamId: string, ids: string[]): Promise<string[]> {
    return runEach(ids, (id) => tasksPartialUpdate(teamId, id, { archived: false }))
}
