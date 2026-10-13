import { z } from 'zod'

import { LocalStorageSlot, localStorageSlot } from 'lib/utils/localStorageSlot'

import { DRAFT_KEY_PREFIX } from './sqlEditorDraftCleanup'

const draftSchema = z
    .object({
        q: z.string(),
        edited_history_id: z.string().optional(),
        baseline_query: z.string().optional(),
    })
    .passthrough()
    .nullable()

interface SQLEditorDraftStorage extends LocalStorageSlot<z.infer<typeof draftSchema>> {
    get: (currentTabOnly?: boolean) => z.infer<typeof draftSchema>
}

export function sqlEditorDraftStorage(
    userUuid: string | undefined,
    teamId: number | null,
    target: string
): SQLEditorDraftStorage | null {
    if (!userUuid || !teamId) {
        return null
    }

    const key = `${DRAFT_KEY_PREFIX}${userUuid}:${teamId}:${target}`
    const localDraft = localStorageSlot(key, draftSchema)
    return {
        get: (currentTabOnly = false) => {
            try {
                const raw = sessionStorage.getItem(key)
                if (raw !== null) {
                    return draftSchema.parse(JSON.parse(raw))
                }
            } catch {
                // Storage may be disabled, or contain a draft from an incompatible version.
            }
            return currentTabOnly ? null : localDraft.get()
        },
        set: (draft) => {
            // Keep null tombstones: key removal tells other tabs to discard their working copies on logout.
            localDraft.set(draft)
            try {
                // A reload must recover this tab's edits, even if another tab edits the same query.
                sessionStorage.setItem(key, JSON.stringify(draft))
            } catch {
                // The local copy still supports recovery when session storage is unavailable.
            }
        },
    }
}
