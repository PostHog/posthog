import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'

import type { DevTokenApi } from '../generated/api.schemas'
import { devModeLogic } from '../logics/devModeLogic'

const STATUS_TAG: Record<DevTokenApi['status'], { label: string; type: 'success' | 'muted' | 'danger' }> = {
    live: { label: 'Live', type: 'success' },
    expired: { label: 'Expired', type: 'muted' },
    revoked: { label: 'Revoked', type: 'danger' },
}

export function DevModeSetting(): JSX.Element {
    const {
        usage,
        usageLoading,
        minted,
        mintedLoading,
        refusal,
        remainingUsd,
        canMint,
        cliRequest,
        liveTokenCount,
        revoking,
    } = useValues(devModeLogic)
    const { mint, revokeToken, authorizeCli, dismissCliRequest } = useActions(devModeLogic)

    if (refusal && !usage) {
        return <LemonBanner type="warning">{refusal}</LemonBanner>
    }

    return (
        <div className="flex flex-col gap-4">
            {cliRequest ? (
                <LemonBanner type="info" data-attr="ai-gateway-dev-mode-cli-request">
                    <div className="flex flex-col gap-2">
                        <span>
                            <code>hogli gateway:token</code> is asking for a token. Approve only if you just ran that
                            command.
                        </span>
                        <div className="flex flex-wrap gap-2">
                            <LemonButton type="primary" size="small" onClick={authorizeCli}>
                                Approve
                            </LemonButton>
                            <LemonButton type="secondary" size="small" onClick={dismissCliRequest}>
                                Deny
                            </LemonButton>
                        </div>
                    </div>
                </LemonBanner>
            ) : null}

            <p className="mb-0">
                Each token can spend up to ${usage?.token_cap_usd ?? '…'} and expires after{' '}
                {usage ? Math.round(usage.ttl_seconds / 3600) : '…'} hours.
            </p>

            <div className="flex flex-wrap items-center gap-2">
                <LemonButton
                    type="primary"
                    onClick={mint}
                    loading={mintedLoading}
                    disabledReason={
                        usageLoading && !usage
                            ? 'Loading'
                            : !canMint
                              ? `You've reached your $${usage?.daily_cap_usd} limit for the last 24 hours`
                              : undefined
                    }
                    data-attr="ai-gateway-dev-mode-mint"
                >
                    Create token
                </LemonButton>
                {usage ? (
                    <span className="text-secondary">
                        <span translate="no">
                            ${remainingUsd?.toFixed(2)} of ${usage.daily_cap_usd}
                        </span>{' '}
                        left in the last 24 hours
                    </span>
                ) : null}
            </div>

            {minted ? (
                <div className="flex flex-col gap-2">
                    <LemonBanner type="success">Copy this token now. It won't be shown again.</LemonBanner>
                    <CodeSnippet className="ph-no-capture" language={Language.Text} wrap thing="token">
                        {minted.token}
                    </CodeSnippet>
                </div>
            ) : null}

            <LemonTable<DevTokenApi>
                dataSource={usage?.tokens ?? []}
                loading={usageLoading}
                emptyState="No tokens created in the last 24 hours"
                columns={[
                    {
                        title: 'Created',
                        key: 'created_at',
                        render: (_, token) => <TZLabel time={token.created_at} />,
                    },
                    {
                        title: 'Expires',
                        key: 'expires_at',
                        render: (_, token) => (token.expires_at ? <TZLabel time={token.expires_at} /> : null),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, token) => (
                            <LemonTag type={STATUS_TAG[token.status].type}>{STATUS_TAG[token.status].label}</LemonTag>
                        ),
                    },
                    {
                        title: 'Source',
                        key: 'client',
                        render: (_, token) => <LemonTag>{token.client === 'cli' ? 'CLI' : 'Web'}</LemonTag>,
                    },
                    {
                        title: 'Spend limit',
                        key: 'cap_usd',
                        render: (_, token) => <span translate="no">${token.cap_usd}</span>,
                    },
                    {
                        title: 'Left',
                        key: 'remaining_usd',
                        tooltip: 'Budget left on a live token, net of requests still in flight.',
                        render: (_, token) =>
                            token.status !== 'live' ? null : token.remaining_usd != null ? (
                                <span translate="no">${Number(token.remaining_usd).toFixed(4)}</span>
                            ) : (
                                <span className="text-secondary">Unknown</span>
                            ),
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, token) =>
                            token.status === 'live' ? (
                                <LemonButton
                                    status="danger"
                                    size="small"
                                    onClick={() => revokeToken(token.id)}
                                    loading={revoking?.id === token.id}
                                    disabledReason={revoking ? 'Revoking' : undefined}
                                >
                                    Revoke
                                </LemonButton>
                            ) : null,
                    },
                ]}
            />
            {liveTokenCount > 1 ? (
                <div>
                    <LemonButton
                        status="danger"
                        type="secondary"
                        size="small"
                        onClick={() => revokeToken(null)}
                        loading={revoking?.id === null}
                        disabledReason={revoking ? 'Revoking' : undefined}
                    >
                        Revoke all
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}
