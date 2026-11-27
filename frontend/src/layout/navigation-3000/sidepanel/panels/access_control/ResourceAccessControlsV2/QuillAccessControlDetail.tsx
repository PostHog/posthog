import { useValues } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { accessControlsLogic } from './accessControlsLogic'
import type { AccessDetailSubjectScope } from './accessDetailLogic'
import { getEntryId, isMemberEntry, subjectDisabledReason } from './helpers'
import { QuillMemberAccessHeader } from './QuillMemberAccessHeader'
import { QuillObjectAccessRules } from './QuillObjectAccessRules'
import { QuillProductAccessRules } from './QuillProductAccessRules'
import { QuillProjectAccessItem } from './QuillProjectAccessItem'
import { QuillPropertyAccessRules } from './QuillPropertyAccessRules'
import { QuillRoleAccessHeader } from './QuillRoleAccessHeader'
import type { AccessControlSettingsEntry } from './types'

/** Everything one member or role can reach in the project, editable in place. */
export function QuillAccessControlDetail({
    projectId,
    scopeType,
    entry,
}: {
    projectId: string
    scopeType: AccessDetailSubjectScope
    entry: AccessControlSettingsEntry
}): JSX.Element {
    const subjectId = getEntryId(entry)
    const subjectNoun = scopeType === 'role' ? 'role' : 'member'
    const { canEdit, terraformDisabledReason } = useValues(accessControlsLogic({ projectId }))
    const { user } = useValues(userLogic)

    // One gate for every control, so the whole panel greys out together (permissions, self-edits, org admins
    // who always have full access)
    const cannotEditReason = terraformDisabledReason ?? subjectDisabledReason(entry, canEdit, user?.uuid)

    return (
        <div className="flex flex-col gap-6">
            {isMemberEntry(entry) ? <QuillMemberAccessHeader member={entry} /> : <QuillRoleAccessHeader role={entry} />}

            <QuillProjectAccessItem
                projectId={projectId}
                scopeType={scopeType}
                entry={entry}
                cannotEditReason={cannotEditReason}
            />

            <QuillProductAccessRules
                projectId={projectId}
                scopeType={scopeType}
                entry={entry}
                subjectNoun={subjectNoun}
                cannotEditReason={cannotEditReason}
            />

            <QuillObjectAccessRules
                projectId={projectId}
                scopeType={scopeType}
                subjectId={subjectId}
                subjectNoun={subjectNoun}
                canEdit={!cannotEditReason}
                cannotEditReason={cannotEditReason}
            />

            <QuillPropertyAccessRules
                projectId={projectId}
                scopeType={scopeType}
                subjectId={subjectId}
                subjectNoun={subjectNoun}
                canEdit={!cannotEditReason}
                cannotEditReason={cannotEditReason}
            />
        </div>
    )
}
