import { useValues } from 'kea'

import { fullName } from 'lib/utils/strings'

import { membersLogic } from '~/models/membersLogic'

import type { AccountNotesViewState } from './accountNotesLogic'
import { describeAccountNotesView } from './accountNotesViewsLogic'

interface AccountNotesViewSummaryProps {
    state: AccountNotesViewState
    scope: 'notes_tab' | 'account'
}

export function AccountNotesViewSummary({ state, scope }: AccountNotesViewSummaryProps): JSX.Element {
    const { meFirstMembers } = useValues(membersLogic)
    const { applied, teamTabOnly } = describeAccountNotesView(
        state,
        (userId) => {
            const member = meFirstMembers.find((candidate) => candidate.user.id === userId)
            return member ? fullName(member.user) || member.user.email : `user ${userId}`
        },
        scope
    )

    return (
        <div className="space-y-1" data-attr="account-notes-view-summary">
            <ul className="list-disc pl-4 space-y-0.5">
                {applied.map((line) => (
                    <li key={line}>{line}</li>
                ))}
            </ul>
            {teamTabOnly.length > 0 && (
                <div className="text-secondary text-xs">
                    Applies on the team Notes tab only: {teamTabOnly.join(', ')}
                </div>
            )}
        </div>
    )
}
