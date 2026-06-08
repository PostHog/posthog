import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonTable, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils'
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

export function CredentialsReviewList(): JSX.Element {
    const { keys, keysLoading } = useValues(personalAPIKeysLogic)
    const { deleteKey } = useActions(personalAPIKeysLogic)

    return (
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
            emptyState="No API keys found."
        />
    )
}
