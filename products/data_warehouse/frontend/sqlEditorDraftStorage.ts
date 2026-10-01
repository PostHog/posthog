import { z } from 'zod'

import { LocalStorageSlot, localStorageSlot } from 'lib/utils/localStorageSlot'

const draftSchema = z
    .object({
        q: z.string(),
        edited_history_id: z.string().optional(),
    })
    .passthrough()
    .nullable()

export function sqlEditorDraftStorage(
    userUuid: string | undefined,
    teamId: number | null,
    target: string
): LocalStorageSlot<z.infer<typeof draftSchema>> | null {
    if (!userUuid || !teamId) {
        return null
    }

    return localStorageSlot(`sql-editor-draft:${userUuid}:${teamId}:${target}`, draftSchema)
}
