import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
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
    const { filteredKeys, keysLoading, search, keyActionInFlight, bulkSummary, rollAllRetrySince } = useValues(
        organizationPersonalAPIKeysLogic
    )
    const { setSearch, rollKey, revokeKey, rollAllKeys, revokeAllKeys } = useActions(organizationPersonalAPIKeysLogic)
    // The in-flight marker names the target ('all' for a bulk action) but not the action, so this records the bulk
    // action to put the spinner on the right button. It never needs a reset, because a spinner also needs the marker.
    const [confirmedBulkAction, setConfirmedBulkAction] = useState<KeyAction | null>(null)

    const runBulkAction = (action: KeyAction, dispatch: () => void): void => {
        setConfirmedBulkAction(action)
        dispatch()
    }
    const isBulkRunning = (action: KeyAction): boolean =>
        keyActionInFlight === ALL_KEYS && confirmedBulkAction === action
    // A finished action clears its in-flight marker before its reload of the list ends. The loading check keeps the
    // buttons disabled on the stale list until the reload ends.
    const actionDisabledReason =
        keyActionInFlight !== null ? 'Wait for the current action to finish' : keysLoading ? 'Loading keys' : null
    const bulkDisabledReason =
        actionDisabledReason ??
        (bulkSummary.total === 0 ? 'No personal API keys have access to this organization' : null)

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
                const running = keyActionInFlight === key.id
                return (
                    <More
                        loading={running}
                        disabledReason={running ? null : actionDisabledReason}
                        aria-label={`Actions for key ${key.mask_value}`}
                        data-attr="organization-personal-api-key-actions"
                        overlay={
                            <>
                                <LemonButton
                                    fullWidth
                                    onClick={() => openRollKeyDialog(key, ownerLabel(key.owner), () => rollKey(key.id))}
                                    data-attr="organization-personal-api-key-roll"
                                >
                                    Roll key
                                </LemonButton>
                                <LemonButton
                                    fullWidth
                                    status="danger"
                                    onClick={() =>
                                        openRevokeKeyDialog(key, ownerLabel(key.owner), () => revokeKey(key.id))
                                    }
                                    data-attr="organization-personal-api-key-revoke"
                                >
                                    Revoke key
                                </LemonButton>
                            </>
                        }
                    />
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
                        loading={isBulkRunning('roll')}
                        disabledReason={isBulkRunning('roll') ? null : bulkDisabledReason}
                        onClick={() =>
                            openRollAllKeysDialog(bulkSummary, search, rollAllRetrySince, () =>
                                runBulkAction('roll', rollAllKeys)
                            )
                        }
                        data-attr="organization-personal-api-keys-roll-all"
                    >
                        Roll all keys
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        loading={isBulkRunning('revoke')}
                        disabledReason={isBulkRunning('revoke') ? null : bulkDisabledReason}
                        onClick={() =>
                            openRevokeAllKeysDialog(bulkSummary, search, () => runBulkAction('revoke', revokeAllKeys))
                        }
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
                rowKey="id"
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
