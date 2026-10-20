import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'

import type { DevTokenApi } from '../generated/api.schemas'
import { devModeLogic, envSnippet } from '../logics/devModeLogic'

export function DevModeSetting(): JSX.Element {
    const { usage, usageLoading, minted, mintedLoading, refusal, remainingUsd, canMint, cliRequest } =
        useValues(devModeLogic)
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
                            A <code>posthog-cli</code> on this computer is asking for a developer mode token. Approve
                            only if you just ran the command yourself.
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
                Mint a short-lived AI gateway token for local development. Every request made with it is attributed to
                you. Each token can spend up to ${usage?.token_cap_usd ?? '…'} and lasts{' '}
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
                              ? 'Your developer mode spend for the last 24 hours is at the daily limit'
                              : undefined
                    }
                    data-attr="ai-gateway-dev-mode-mint"
                >
                    Generate token
                </LemonButton>
                {usage ? (
                    <span className="text-secondary">
                        <span translate="no">
                            ${remainingUsd?.toFixed(2)} of ${usage.daily_cap_usd}
                        </span>{' '}
                        left today
                    </span>
                ) : null}
            </div>

            {minted ? (
                <div className="flex flex-col gap-2">
                    <LemonBanner type="success">
                        Copy this token now. PostHog only stores its hash, so it cannot be shown again.
                    </LemonBanner>
                    <CodeSnippet language={Language.Bash} wrap thing="environment variables">
                        {envSnippet(minted)}
                    </CodeSnippet>
                </div>
            ) : null}

            <LemonTable<DevTokenApi>
                dataSource={usage?.tokens ?? []}
                loading={usageLoading}
                emptyState="No live tokens"
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
                        title: 'From',
                        key: 'client',
                        render: (_, token) => <LemonTag>{token.client === 'cli' ? 'CLI' : 'Web'}</LemonTag>,
                    },
                    {
                        title: 'Cap',
                        key: 'cap_usd',
                        render: (_, token) => <span translate="no">${token.cap_usd}</span>,
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, token) => (
                            <LemonButton status="danger" size="small" onClick={() => revokeToken(token.id)}>
                                Revoke
                            </LemonButton>
                        ),
                    },
                ]}
            />
            {usage && usage.tokens.length > 1 ? (
                <div>
                    <LemonButton status="danger" type="secondary" size="small" onClick={() => revokeToken(null)}>
                        Revoke all
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}
