import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { membershipLevelToName } from 'lib/utils/permissioning'

import type { OrganizationNotificationMemberApi } from '~/generated/core/api.schemas'

import type { NotificationConcept, NotificationRuleValue } from '../shared/notificationSettingDescriptors'
import { MEMBERS_PER_PAGE, listKey, notificationGovernanceLogic, ruleFor } from './notificationGovernanceLogic'

const OPTIONS: { value: NotificationRuleValue; label: string }[] = [
    { value: 'none', label: 'No override' },
    { value: 'on', label: 'Always on' },
    { value: 'off', label: 'Always off' },
]

export function NotificationMemberList({
    concept,
    scopeId,
    members,
}: {
    concept: NotificationConcept
    scopeId: string
    members: OrganizationNotificationMemberApi[]
}): JSX.Element {
    const { pendingRules, savedRules, listViews, savingChanges } = useValues(notificationGovernanceLogic)
    const { setRule, setRuleForMany, setListQuery, setListPage } = useActions(notificationGovernanceLogic)

    const list = listKey(concept.setting, scopeId)
    const view = listViews[list] ?? { query: '', page: 0 }
    const needle = view.query.trim().toLowerCase()
    const matching = needle
        ? members.filter((member) =>
              `${member.first_name} ${member.last_name} ${member.email}`.toLowerCase().includes(needle)
          )
        : members

    const pages = Math.max(1, Math.ceil(matching.length / MEMBERS_PER_PAGE))
    const page = Math.min(view.page, pages - 1)
    const start = page * MEMBERS_PER_PAGE
    const shown = matching.slice(start, start + MEMBERS_PER_PAGE)
    const editableIds = matching.filter((member) => member.editable).map((member) => member.user_id)

    return (
        <div className="deprecated-space-y-2">
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search members"
                    value={view.query}
                    onChange={(query) => setListQuery(list, query)}
                    className="w-56"
                    data-attr="notification-governance-search"
                />
                <span className="text-muted text-xs ml-auto">
                    {needle
                        ? `Set the ${matching.length} matching ${matching.length === 1 ? 'member' : 'members'} to`
                        : `Set all ${members.length} members to`}
                </span>
                {OPTIONS.map((option) => (
                    <LemonButton
                        key={option.value}
                        size="xsmall"
                        type="secondary"
                        onClick={() => setRuleForMany(concept.setting, scopeId, editableIds, option.value)}
                        disabledReason={savingChanges ? 'Saving' : undefined}
                        data-attr={`notification-governance-bulk-${option.value}`}
                    >
                        {option.label}
                    </LemonButton>
                ))}
            </div>

            {shown.length === 0 ? (
                <p className="text-muted text-sm">No members match that search.</p>
            ) : (
                <div className="flex flex-col gap-1">
                    {shown.map((member) => {
                        const name = `${member.first_name} ${member.last_name}`.trim()
                        return (
                            <div key={member.user_id} className="flex items-center gap-2">
                                <span className="flex-1 flex items-center gap-2 min-w-0">
                                    <span className="truncate">{name || member.email}</span>
                                    {!!name && <span className="text-muted text-xs truncate">{member.email}</span>}
                                    <LemonTag type="muted">
                                        {membershipLevelToName.get(member.organization_membership_level)}
                                    </LemonTag>
                                </span>
                                <LemonSegmentedButton
                                    size="xsmall"
                                    value={ruleFor(pendingRules, savedRules, concept.setting, scopeId, member.user_id)}
                                    onChange={(value) => setRule(concept.setting, scopeId, member.user_id, value)}
                                    options={OPTIONS}
                                    disabledReason={
                                        !member.editable
                                            ? 'This member has a higher organization access level than you'
                                            : savingChanges
                                              ? 'Saving'
                                              : undefined
                                    }
                                />
                            </div>
                        )
                    })}
                </div>
            )}

            <div className="flex items-center gap-2 text-muted text-xs">
                <span className="mr-auto">
                    {matching.length > 0 &&
                        `Showing ${start + 1} to ${Math.min(start + MEMBERS_PER_PAGE, matching.length)} of ${
                            matching.length
                        }${needle ? ` matching, out of ${members.length}` : ''}`}
                </span>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() => setListPage(list, page - 1)}
                    disabledReason={page === 0 ? 'On the first page' : undefined}
                >
                    Previous
                </LemonButton>
                <span>
                    Page {page + 1} of {pages}
                </span>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() => setListPage(list, page + 1)}
                    disabledReason={page >= pages - 1 ? 'On the last page' : undefined}
                >
                    Next
                </LemonButton>
            </div>
        </div>
    )
}
