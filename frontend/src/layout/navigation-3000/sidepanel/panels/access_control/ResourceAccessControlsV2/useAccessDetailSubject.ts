import { useValues } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { accessControlsLogic } from './accessControlsLogic'
import type { AccessDetailSubjectScope } from './accessDetailLogic'
import { getEntryId, subjectDisabledReason } from './helpers'
import type { AccessControlSettingsEntry } from './types'

export interface AccessDetailSubjectInfo {
    subjectId: string
    subjectNoun: 'role' | 'member'
    /** One gate for every control, so the whole detail greys out together. */
    cannotEditReason: string | undefined
}

export function useAccessDetailSubject(
    projectId: string,
    scopeType: AccessDetailSubjectScope,
    entry: AccessControlSettingsEntry
): AccessDetailSubjectInfo {
    const { canEdit, terraformDisabledReason } = useValues(accessControlsLogic({ projectId }))
    const { user } = useValues(userLogic)

    return {
        subjectId: getEntryId(entry),
        subjectNoun: scopeType === 'role' ? 'role' : 'member',
        cannotEditReason: terraformDisabledReason ?? subjectDisabledReason(entry, canEdit, user?.uuid),
    }
}
