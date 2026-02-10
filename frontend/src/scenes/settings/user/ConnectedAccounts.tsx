import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { IconGitlab, IconGoogle } from 'lib/lemon-ui/icons'

import { SocialConnection, connectedAccountsLogic } from './connectedAccountsLogic'

function ProviderIcon({ provider }: { provider: string }): JSX.Element | null {
    if (provider === 'github') {
        return <IconGithub className="text-xl" />
    } else if (provider === 'google-oauth2') {
        return <IconGoogle className="text-xl" />
    } else if (provider === 'gitlab') {
        return <IconGitlab className="text-xl" />
    }
    return null
}

function providerDisplayName(provider: string): string {
    const names: Record<string, string> = {
        github: 'GitHub',
        'google-oauth2': 'Google',
        gitlab: 'GitLab',
    }
    return names[provider] || provider
}

export function ConnectedAccounts(): JSX.Element {
    const { connections, connectionsLoading, availableProviders, canUnlink } = useValues(connectedAccountsLogic)
    const { unlinkConnection } = useActions(connectedAccountsLogic)

    if (connectionsLoading && connections.length === 0) {
        return (
            <div className="space-y-4">
                <LemonSkeleton className="h-32" />
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <p className="text-muted">
                Link your social accounts for single sign-on. You can use any linked account to log in to PostHog.
            </p>

            {connections.length > 0 && (
                <LemonTable
                    dataSource={connections}
                    columns={[
                        {
                            title: 'Provider',
                            dataIndex: 'provider',
                            render: (_, connection: SocialConnection) => (
                                <div className="flex items-center gap-2">
                                    <ProviderIcon provider={connection.provider} />
                                    <span className="font-medium">{providerDisplayName(connection.provider)}</span>
                                </div>
                            ),
                        },
                        {
                            title: 'Account',
                            dataIndex: 'uid',
                            render: (uid) => <span className="text-muted">{String(uid)}</span>,
                        },
                        {
                            title: 'Linked on',
                            dataIndex: 'created',
                            render: (created) =>
                                created ? <TZLabel time={String(created)} /> : <span className="text-muted">-</span>,
                        },
                        {
                            title: '',
                            render: (_, connection: SocialConnection) => {
                                const canRemove = canUnlink(connection.id)
                                return (
                                    <Tooltip
                                        title={
                                            !canRemove
                                                ? 'Cannot unlink your only login method. Set a password first.'
                                                : undefined
                                        }
                                    >
                                        <LemonButton
                                            type="secondary"
                                            status="danger"
                                            size="small"
                                            onClick={() => unlinkConnection(connection.id)}
                                            disabledReason={
                                                !canRemove
                                                    ? 'Cannot unlink your only login method. Set a password first.'
                                                    : undefined
                                            }
                                        >
                                            Unlink
                                        </LemonButton>
                                    </Tooltip>
                                )
                            },
                        },
                    ]}
                    loading={connectionsLoading}
                    rowKey="id"
                    emptyState="No connected accounts"
                />
            )}

            {availableProviders.length > 0 && (
                <div className="flex gap-2 flex-wrap">
                    {availableProviders.map(({ key, name }) => {
                        const alreadyLinked = connections.some((c) => c.provider === key)
                        return (
                            <LemonButton
                                key={key}
                                type="secondary"
                                icon={<ProviderIcon provider={key} />}
                                onClick={() => {
                                    // Full page navigation to initiate OAuth flow
                                    window.location.href = `/api/social/connect/${key}/`
                                }}
                                sideIcon={
                                    alreadyLinked ? (
                                        <LemonTag type="completion" size="small">
                                            Linked
                                        </LemonTag>
                                    ) : null
                                }
                            >
                                {alreadyLinked ? `Link another ${name} account` : `Link ${name} account`}
                            </LemonButton>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
