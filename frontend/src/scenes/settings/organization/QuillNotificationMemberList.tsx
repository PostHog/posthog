import { useActions, useValues } from 'kea'

import { Badge, Button, InputGroup, InputGroupInput, Text, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { membershipLevelToName } from 'lib/utils/permissioning'
import { pluralize } from 'lib/utils/strings'

import type { NotificationConcept, NotificationRuleValue } from '../shared/notificationSettingDescriptors'
import { MEMBERS_PER_PAGE, listKey, notificationGovernanceLogic, ruleFor } from './notificationGovernanceLogic'
import { NOTIFICATION_RULE_OPTIONS } from './NotificationMemberList'

export function QuillNotificationMemberList({
    concept,
    scopeId,
}: {
    concept: NotificationConcept
    scopeId: string
}): JSX.Element {
    const { pendingRules, savedRules, savingChanges, memberListFor } = useValues(notificationGovernanceLogic)
    const { setRule, setRuleForMany, setListQuery, setListPage } = useActions(notificationGovernanceLogic)

    const list = listKey(concept.setting, scopeId)
    const { query, searching, total, matching, shown, editableIds, page, pages, start } = memberListFor(list)
    const savingReason = savingChanges ? 'Saving' : undefined

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <InputGroup size="sm" className="w-56">
                    <InputGroupInput
                        type="search"
                        placeholder="Search members"
                        aria-label="Search members"
                        value={query}
                        onChange={(event) => setListQuery(list, event.target.value)}
                        data-attr="notification-governance-search"
                    />
                </InputGroup>
                <Text size="xs" variant="muted" render={<span />} className="m-0 ml-auto" translate="no">
                    {searching
                        ? `Set ${pluralize(editableIds.length, 'matching member')} to`
                        : `Set all ${pluralize(editableIds.length, 'member')} to`}
                </Text>
                {NOTIFICATION_RULE_OPTIONS.map((option) => (
                    <Button
                        key={option.value}
                        size="sm"
                        variant="outline"
                        onClick={() => setRuleForMany(concept.setting, scopeId, editableIds, option.value)}
                        disabledReason={savingReason}
                        data-attr={`notification-governance-bulk-${option.value}`}
                    >
                        {option.label}
                    </Button>
                ))}
            </div>

            {shown.length === 0 ? (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    No members match that search.
                </Text>
            ) : (
                <div className="flex flex-col gap-1">
                    {shown.map((member) => {
                        const name = `${member.first_name} ${member.last_name}`.trim()
                        const rule = ruleFor(pendingRules, savedRules, concept.setting, scopeId, member.user_id)
                        const disabledReason = !member.editable
                            ? 'This member has a higher organization access level than you'
                            : savingReason

                        return (
                            <div key={member.user_id} className="flex flex-wrap items-center gap-2">
                                <span className="flex-1 flex items-center gap-2 min-w-0">
                                    <Text size="xs" render={<span />} className="m-0 truncate">
                                        {name || member.email}
                                    </Text>
                                    {!!name && (
                                        <Text size="xs" variant="muted" render={<span />} className="m-0 truncate">
                                            {member.email}
                                        </Text>
                                    )}
                                    <Badge>{membershipLevelToName.get(member.organization_membership_level)}</Badge>
                                </span>
                                <ToggleGroup
                                    variant="outline"
                                    size="sm"
                                    aria-label={`Override for ${name || member.email}`}
                                    value={[rule]}
                                    onValueChange={(next: string[]) => {
                                        const picked = next[0] as NotificationRuleValue | undefined
                                        if (picked && picked !== rule) {
                                            setRule(concept.setting, scopeId, member.user_id, picked)
                                        }
                                    }}
                                >
                                    {NOTIFICATION_RULE_OPTIONS.map((option) => (
                                        <ToggleGroupItem
                                            key={option.value}
                                            value={option.value}
                                            disabledReason={disabledReason}
                                        >
                                            {option.label}
                                        </ToggleGroupItem>
                                    ))}
                                </ToggleGroup>
                            </div>
                        )
                    })}
                </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
                <Text size="xs" variant="muted" render={<span />} className="m-0 mr-auto" translate="no">
                    {matching > 0 &&
                        `Showing ${start + 1} to ${Math.min(start + MEMBERS_PER_PAGE, matching)} of ${matching}${
                            searching ? ` matching, out of ${total}` : ''
                        }`}
                </Text>
                <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setListPage(list, page - 1)}
                    disabledReason={page === 0 ? 'On the first page' : undefined}
                >
                    Previous
                </Button>
                <Text size="xs" variant="muted" render={<span />} className="m-0" translate="no">
                    {`Page ${page + 1} of ${pages}`}
                </Text>
                <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setListPage(list, page + 1)}
                    disabledReason={page >= pages - 1 ? 'On the last page' : undefined}
                >
                    Next
                </Button>
            </div>
        </div>
    )
}
