import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { fullName } from 'lib/utils/strings'
import { TagList } from 'scenes/settings/user/PersonalAPIKeys'
import { ScopeGroupSummary } from 'scenes/settings/user/scopes/ScopeGroupSummary'

import type { OrganizationPersonalAPIKeyApi } from 'products/platform_features/frontend/generated/api.schemas'

import {
    openRevokeAllKeysDialog,
    openRevokeKeyDialog,
    openRollAllKeysDialog,
    openRollKeyDialog,
} from './organizationPersonalAPIKeyDialogs'
import { ALL_KEYS, KeyAction, organizationPersonalAPIKeysLogic } from './organizationPersonalAPIKeysLogic'

function AccessScope({ accessScope }: { accessScope: OrganizationPersonalAPIKeyApi['access_scope'] }): JSX.Element {
    if (accessScope.type === 'all') {
        return <span className="text-muted">All projects (unscoped)</span>
    }
    if (accessScope.type === 'organization') {
        return <span>Organization-wide</span>
    }
    return <TagList tags={(accessScope.projects ?? []).map((project) => project.name)} />
}

function ownerLabel(owner: OrganizationPersonalAPIKeyApi['owner']): string {
    return fullName(owner) || owner.email
}

export function OrganizationPersonalAPIKeysTable(): JSX.Element {
    const { filteredKeys, keysLoading, search, keyActionInFlight, bulkSummary } = useValues(
        organizationPersonalAPIKeysLogic
    )
    const { setSearch, rollKey, revokeKey, rollAllKeys, revokeAllKeys } = useActions(organizationPersonalAPIKeysLogic)
    // The in-flight marker names the target (a key id or 'all') but not the action, so this records the action to
    // put the spinner on the right button. It never needs a reset, because a spinner also needs the marker to match.
    const [confirmedAction, setConfirmedAction] = useState<KeyAction | null>(null)

    const runAction = (action: KeyAction, dispatch: () => void): void => {
        setConfirmedAction(action)
        dispatch()
    }
    const isRunning = (target: string, action: KeyAction): boolean =>
        keyActionInFlight === target && confirmedAction === action
    const actionInFlightReason = keyActionInFlight !== null ? 'Wait for the current action to finish' : null
    const bulkDisabledReason =
        actionInFlightReason ??
        (bulkSummary.total === 0
            ? keysLoading
                ? 'Loading keys'
                : 'No personal API keys have access to this organization'
            : null)

    const columns: LemonTableColumns<OrganizationPersonalAPIKeyApi> = [
        {
            title: 'Owner',
            key: 'owner',
            sorter: (a, b) => ownerLabel(a.owner).localeCompare(ownerLabel(b.owner)),
            render: (_, key) => (
                <div className="flex flex-col">
                    <span>{ownerLabel(key.owner)}</span>
                    <span className="text-muted text-xs">{key.owner.email}</span>
                </div>
            ),
        },
        {
            title: 'Masked value',
            key: 'mask_value',
            sorter: (a, b) => a.mask_value.localeCompare(b.mask_value),
            render: (_, key) => <span className="font-mono">{key.mask_value}</span>,
        },
        {
            title: 'Scopes',
            key: 'scopes',
            render: (_, key) => <TagList tags={[...key.scopes]} tooltip={<ScopeGroupSummary scopes={key.scopes} />} />,
        },
        {
            title: 'Access scope',
            key: 'access_scope',
            render: (_, key) => <AccessScope accessScope={key.access_scope} />,
        },
        {
            title: 'Last used',
            key: 'last_used_at',
            sorter: (a, b) => new Date(a.last_used_at ?? 0).getTime() - new Date(b.last_used_at ?? 0).getTime(),
            render: (_, key) =>
                key.last_used_at ? <TZLabel time={key.last_used_at} /> : <span className="text-muted">Never</span>,
        },
        {
            title: 'Created',
            key: 'created_at',
            sorter: (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
            render: (_, key) => <TZLabel time={key.created_at} />,
        },
        {
            key: 'actions',
            width: 0,
            render: (_, key) => {
                const rolling = isRunning(key.id, 'roll')
                const revoking = isRunning(key.id, 'revoke')
                return (
                    <div className="flex gap-1">
                        <LemonButton
                            type="secondary"
                            size="small"
                            loading={rolling}
                            disabledReason={rolling ? null : actionInFlightReason}
                            onClick={() =>
                                openRollKeyDialog(key, ownerLabel(key.owner), () =>
                                    runAction('roll', () => rollKey(key.id))
                                )
                            }
                            data-attr="organization-personal-api-key-roll"
                        >
                            Roll
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            loading={revoking}
                            disabledReason={revoking ? null : actionInFlightReason}
                            onClick={() =>
                                openRevokeKeyDialog(key, ownerLabel(key.owner), () =>
                                    runAction('revoke', () => revokeKey(key.id))
                                )
                            }
                            data-attr="organization-personal-api-key-revoke"
                        >
                            Revoke
                        </LemonButton>
                    </div>
                )
            },
        },
    ]

    return (
        <>
            <div className="flex flex-wrap items-center gap-2 mb-2">
                <LemonInput
                    type="search"
                    placeholder="Search by name, email, or scope"
                    value={search}
                    onChange={setSearch}
                    className="grow min-w-60 max-w-80"
                />
                <div className="flex flex-wrap gap-2 ml-auto">
                    <LemonButton
                        type="secondary"
                        loading={isRunning(ALL_KEYS, 'roll')}
                        disabledReason={isRunning(ALL_KEYS, 'roll') ? null : bulkDisabledReason}
                        onClick={() => openRollAllKeysDialog(bulkSummary, () => runAction('roll', rollAllKeys))}
                        data-attr="organization-personal-api-keys-roll-all"
                    >
                        Roll all keys
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        loading={isRunning(ALL_KEYS, 'revoke')}
                        disabledReason={isRunning(ALL_KEYS, 'revoke') ? null : bulkDisabledReason}
                        onClick={() => openRevokeAllKeysDialog(bulkSummary, () => runAction('revoke', revokeAllKeys))}
                        data-attr="organization-personal-api-keys-revoke-all"
                    >
                        Revoke all keys
                    </LemonButton>
                </div>
            </div>
            <LemonTable
                dataSource={filteredKeys}
                loading={keysLoading}
                columns={columns}
                rowKey={(key) => `${key.owner.email}-${key.mask_value}-${key.created_at}`}
                pagination={{ pageSize: 25 }}
                emptyState={
                    search.trim()
                        ? 'No personal API keys match your search.'
                        : 'No personal API keys have access to this organization.'
                }
            />
        </>
    )
}
