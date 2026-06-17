import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonTable, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { type PasskeyCredential, passkeySettingsLogic } from 'scenes/settings/user/passkeySettingsLogic'
import { personalAPIKeysLogic } from 'scenes/settings/user/personalAPIKeysLogic'

import { PersonalAPIKeyType } from '~/types'

function scopeSummary(key: PersonalAPIKeyType): string {
    if (!key.scopes?.length) {
        return 'No access'
    }
    if (key.scopes.includes('*')) {
        return 'Full access'
    }
    if (key.scopes.length <= 3) {
        return key.scopes.join(', ')
    }
    return `${key.scopes.slice(0, 3).join(', ')} + ${key.scopes.length - 3} more`
}

function teamScopeSummary(key: PersonalAPIKeyType): string {
    const orgs = key.scoped_organizations?.length ?? 0
    const teams = key.scoped_teams?.length ?? 0
    if (orgs === 0 && teams === 0) {
        return 'All projects'
    }
    const parts: string[] = []
    if (orgs > 0) {
        parts.push(`${orgs} organization${orgs === 1 ? '' : 's'}`)
    }
    if (teams > 0) {
        parts.push(`${teams} project${teams === 1 ? '' : 's'}`)
    }
    return parts.join(', ')
}

function passkeyTypeLabel(passkey: PasskeyCredential): string {
    switch (passkey.authenticator_type) {
        case 'platform':
            return 'This device'
        case 'hardware':
            return 'Hardware key'
        case 'hybrid':
            return 'Cross-device'
        default:
            return 'Unknown'
    }
}

export function CredentialsReviewList(): JSX.Element {
    const { keys, keysLoading } = useValues(personalAPIKeysLogic)
    const { deleteKey } = useActions(personalAPIKeysLogic)
    const { passkeys, passkeysLoading } = useValues(passkeySettingsLogic)
    const { deletePasskey } = useActions(passkeySettingsLogic)

    const showKeys = keysLoading || keys.length > 0
    const showPasskeys = passkeysLoading || passkeys.length > 0

    return (
        <div className="flex flex-col gap-6">
            {showKeys && (
                <section>
                    <h3 className="text-base font-semibold mb-2">Personal API keys</h3>
                    <LemonTable
                        dataSource={keys}
                        loading={keysLoading}
                        rowKey={(key) => key.id}
                        columns={[
                            {
                                title: 'Label',
                                dataIndex: 'label',
                                render: (_, key) => <span className="font-semibold">{key.label}</span>,
                            },
                            {
                                title: 'Access',
                                render: (_, key) => (
                                    <Tooltip title={key.scopes?.join(', ') ?? ''}>
                                        <span>
                                            {scopeSummary(key)} · {teamScopeSummary(key)}
                                        </span>
                                    </Tooltip>
                                ),
                            },
                            {
                                title: 'Created',
                                dataIndex: 'created_at',
                                render: (value) => humanFriendlyDetailedTime(value as string),
                            },
                            {
                                title: '',
                                width: 0,
                                render: (_, key) => (
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        size="small"
                                        onClick={() =>
                                            LemonDialog.open({
                                                title: `Revoke "${key.label}"?`,
                                                description:
                                                    'Any service still using this key will start receiving 401 errors immediately.',
                                                primaryButton: {
                                                    status: 'danger',
                                                    children: 'Revoke',
                                                    onClick: () => deleteKey(key.id),
                                                },
                                            })
                                        }
                                    >
                                        Revoke
                                    </LemonButton>
                                ),
                            },
                        ]}
                    />
                </section>
            )}
            {showPasskeys && (
                <section>
                    <h3 className="text-base font-semibold mb-2">Passkeys</h3>
                    <LemonTable
                        dataSource={passkeys}
                        loading={passkeysLoading}
                        rowKey={(passkey) => passkey.id}
                        columns={[
                            {
                                title: 'Label',
                                dataIndex: 'label',
                                render: (_, passkey) => <span className="font-semibold">{passkey.label}</span>,
                            },
                            {
                                title: 'Type',
                                render: (_, passkey) => passkeyTypeLabel(passkey),
                            },
                            {
                                title: 'Created',
                                dataIndex: 'created_at',
                                render: (value) => humanFriendlyDetailedTime(value as string),
                            },
                            {
                                title: '',
                                width: 0,
                                render: (_, passkey) => (
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        size="small"
                                        onClick={() =>
                                            LemonDialog.open({
                                                title: `Remove "${passkey.label}"?`,
                                                description:
                                                    'Anyone signed in with this passkey will need a new one to log in again.',
                                                primaryButton: {
                                                    status: 'danger',
                                                    children: 'Remove',
                                                    onClick: () => deletePasskey(passkey.id),
                                                },
                                            })
                                        }
                                    >
                                        Remove
                                    </LemonButton>
                                ),
                            },
                        ]}
                    />
                </section>
            )}
        </div>
    )
}
