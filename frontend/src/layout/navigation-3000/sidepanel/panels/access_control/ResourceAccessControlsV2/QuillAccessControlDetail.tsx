import type { AccessDetailSubjectScope } from './accessDetailLogic'
import { isMemberEntry } from './helpers'
import { QuillMemberAccessHeader } from './QuillMemberAccessHeader'
import { QuillObjectAccessRules } from './QuillObjectAccessRules'
import { QuillProductAccessRules } from './QuillProductAccessRules'
import { QuillProjectAccessItem } from './QuillProjectAccessItem'
import { QuillPropertyAccessRules } from './QuillPropertyAccessRules'
import { QuillRoleAccessHeader } from './QuillRoleAccessHeader'
import type { AccessControlSettingsEntry } from './types'
import { useAccessDetailSubject } from './useAccessDetailSubject'

export function QuillAccessControlDetail({
    projectId,
    scopeType,
    entry,
}: {
    projectId: string
    scopeType: AccessDetailSubjectScope
    entry: AccessControlSettingsEntry
}): JSX.Element {
    const { subjectId, subjectNoun, cannotEditReason } = useAccessDetailSubject(projectId, scopeType, entry)

    return (
        <div className="flex flex-col gap-6">
            {isMemberEntry(entry) ? (
                <QuillMemberAccessHeader member={entry} />
            ) : (
                <QuillRoleAccessHeader projectId={projectId} role={entry} />
            )}

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
