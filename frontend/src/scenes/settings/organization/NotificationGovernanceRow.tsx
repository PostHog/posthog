import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight, IconLock } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonTag } from '@posthog/lemon-ui'

import { membershipLevelToName } from 'lib/utils/permissioning'

import { type NotificationSettingDescriptor, checkedToStoredValue } from '../shared/notificationSettingDescriptors'
import { ALL_MEMBERS, notificationGovernanceLogic, resolveControl } from './notificationGovernanceLogic'

function useScopes(descriptor: NotificationSettingDescriptor): { id: string; label: string }[] {
    const { currentOrganization, pipelines } = useValues(notificationGovernanceLogic)

    if (descriptor.scope === 'none') {
        return [{ id: '', label: '' }]
    }
    if (descriptor.scope === 'team') {
        return (currentOrganization?.teams ?? []).map((team) => ({ id: String(team.id), label: team.name }))
    }
    if (descriptor.scope === 'organization') {
        return currentOrganization ? [{ id: currentOrganization.id, label: currentOrganization.name }] : []
    }
    return (pipelines ?? []).map((pipeline) => ({
        id: pipeline.id,
        label: `${pipeline.teamName}: ${pipeline.name}`,
    }))
}

export function NotificationGovernanceRow({
    descriptor,
}: {
    descriptor: NotificationSettingDescriptor
}): JSX.Element | null {
    const { members, pendingChanges, savingChanges } = useValues(notificationGovernanceLogic)
    const { setControl } = useActions(notificationGovernanceLogic)
    const [expanded, setExpanded] = useState(false)
    const scopes = useScopes(descriptor)

    const listedMembers = members ?? []
    if (scopes.length === 0) {
        return null
    }

    const lockedCount = scopes.reduce(
        (total, scope) =>
            total +
            listedMembers.filter((member) => resolveControl(member, descriptor, scope.id, pendingChanges).locked)
                .length,
        0
    )

    return (
        <div className="border rounded p-3 space-y-2">
            <div className="flex items-center justify-between gap-2">
                <LemonButton
                    icon={expanded ? <IconChevronDown /> : <IconChevronRight />}
                    onClick={() => setExpanded(!expanded)}
                    size="small"
                    type="tertiary"
                    className="p-0"
                    data-attr="notification-governance-expand"
                >
                    {descriptor.label}
                </LemonButton>
                <span className="text-muted text-xs">
                    {lockedCount === 0 ? 'Members choose' : `${lockedCount} set by the organization`}
                </span>
            </div>
            <p className="text-muted text-xs mb-0">{descriptor.description}</p>

            {expanded && (
                <div className="ml-6 space-y-3">
                    {scopes.map((scope) => (
                        <div key={scope.id} className="space-y-1">
                            {!!scope.label && <div className="text-sm font-medium">{scope.label}</div>}
                            <div className="flex flex-row items-center gap-4">
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() =>
                                        setControl(
                                            ALL_MEMBERS,
                                            descriptor.setting,
                                            scope.id,
                                            checkedToStoredValue(descriptor, true)
                                        )
                                    }
                                    data-attr="notification-governance-everyone-on"
                                >
                                    Set on for everyone
                                </LemonButton>
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() =>
                                        setControl(
                                            ALL_MEMBERS,
                                            descriptor.setting,
                                            scope.id,
                                            checkedToStoredValue(descriptor, false)
                                        )
                                    }
                                    data-attr="notification-governance-everyone-off"
                                >
                                    Set off for everyone
                                </LemonButton>
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    onClick={() => setControl(ALL_MEMBERS, descriptor.setting, scope.id, null)}
                                    data-attr="notification-governance-everyone-clear"
                                >
                                    Let members choose
                                </LemonButton>
                            </div>

                            <div className="flex flex-col gap-1">
                                {listedMembers.map((member) => {
                                    const state = resolveControl(member, descriptor, scope.id, pendingChanges)
                                    const name = `${member.first_name} ${member.last_name}`.trim()
                                    return (
                                        <LemonCheckbox
                                            key={member.user_id}
                                            id={`governance-${descriptor.setting}-${scope.id}-${member.user_id}`}
                                            data-attr="notification-governance-member"
                                            checked={state.checked}
                                            onChange={(checked) =>
                                                setControl(
                                                    member.user_id,
                                                    descriptor.setting,
                                                    scope.id,
                                                    checkedToStoredValue(descriptor, checked)
                                                )
                                            }
                                            disabledReason={
                                                !member.editable
                                                    ? 'This member has a higher organization access level than you'
                                                    : savingChanges
                                                      ? 'Saving'
                                                      : undefined
                                            }
                                            label={
                                                <div className="flex items-center gap-2">
                                                    <span>{name || member.email}</span>
                                                    {!!name && (
                                                        <span className="text-muted text-xs">{member.email}</span>
                                                    )}
                                                    <LemonTag type="muted">
                                                        {membershipLevelToName.get(
                                                            member.organization_membership_level
                                                        )}
                                                    </LemonTag>
                                                    {state.locked && (
                                                        <LemonTag type="warning" icon={<IconLock />}>
                                                            {state.lockedForEveryone
                                                                ? 'Set for everyone'
                                                                : 'Set by you'}
                                                        </LemonTag>
                                                    )}
                                                </div>
                                            }
                                        />
                                    )
                                })}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
