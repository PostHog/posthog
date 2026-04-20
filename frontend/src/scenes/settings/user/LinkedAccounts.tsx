import { useActions, useValues } from 'kea'
import { useState, useEffect } from 'react'

import { IconCheck, IconLock } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonSkeleton, LemonSwitch, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { SocialLoginIcon } from 'lib/components/SocialLoginButton/SocialLoginIcon'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonBadge } from 'lib/lemon-ui/LemonBadge'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { SSOProvider } from '~/types'

import { LinkedAccount, linkedAccountsLogic } from './linkedAccountsLogic'

function StatusTag({ account }: { account: LinkedAccount }): JSX.Element | null {
    if (account.connected && !account.can_disconnect) {
        return (
            <LemonTag type="warning" size="small" icon={<IconLock />}>
                Required by organization
            </LemonTag>
        )
    }
    return null
}

function badgeTooltipFor(account: LinkedAccount): string {
    if (account.login_enabled) {
        return account.can_disconnect
            ? `Connected & can be used to sign in to PostHog`
            : `Connected & required to sign in to PostHog by your organization`
    }
    return 'Connected & used for identity only, not sign-in'
}

function ProviderAvatar({ account }: { account: LinkedAccount }): JSX.Element {
    return (
        <div className="relative shrink-0">
            <div className="flex h-10 w-10 items-center justify-center rounded-md border bg-surface-secondary text-2xl">
                <SocialLoginIcon provider={account.provider as SSOProvider} />
            </div>
            {account.connected ? (
                // Wrap the badge in a pointer-events-auto span so the tooltip fires; LemonBadge itself
                // has `pointer-events: none` globally and we don't want to override that as a one-off.
                <Tooltip title={badgeTooltipFor(account)} delayMs={0}>
                    <span className="absolute -top-1 -right-1 inline-flex pointer-events-auto">
                        <LemonBadge
                            status="success"
                            size="small"
                            position="none"
                            content={
                                account.login_enabled ? (
                                    <span className="flex items-center justify-center text-[0.625rem]">
                                        <IconCheck />
                                    </span>
                                ) : (
                                    <IconLink />
                                )
                            }
                        />
                    </span>
                </Tooltip>
            ) : null}
        </div>
    )
}

function GithubSignInToggle({
    account,
    onChange,
}: {
    account: LinkedAccount
    onChange: (value: boolean) => void
}): JSX.Element {
    const [optimisticLoginEnabled, setOptimisticLoginEnabled] = useState(account.login_enabled)

    useEffect(() => {
        setOptimisticLoginEnabled(account.login_enabled)
    }, [account.login_enabled])

    const tooltip = !account.can_enable_login
        ? "Your organization requires SSO — sign-in with GitHub can't be enabled."
        : account.login_enabled
          ? 'GitHub is linked for identity & login.'
          : 'GitHub is linked for identity only.'
    return (
        <Tooltip title={tooltip}>
            <span className="inline-flex items-center">
                <LemonSwitch
                    checked={optimisticLoginEnabled}
                    disabledReason={!account.can_enable_login ? 'Blocked by SSO enforcement' : undefined}
                    loading={optimisticLoginEnabled !== account.login_enabled}
                    onChange={(value) => {
                        setOptimisticLoginEnabled(value)
                        onChange(value)
                    }}
                    label="Allow login"
                    bordered={false}
                />
            </span>
        </Tooltip>
    )
}

function LinkedAccountRow({
    account,
    onSetLoginEnabled,
    onDisconnect,
    onConnect,
}: {
    account: LinkedAccount
    onSetLoginEnabled: (provider: string, value: boolean) => void
    onDisconnect: (account: LinkedAccount) => void
    onConnect: (account: LinkedAccount) => void
}): JSX.Element {
    const isConnected = account.connected
    const dimmedClass = isConnected ? '' : ' opacity-60'
    return (
        <div className="flex items-center gap-4 px-4 py-3">
            <div className={'shrink-0' + dimmedClass}>
                <ProviderAvatar account={account} />
            </div>
            <div className={'min-w-0 flex-1' + dimmedClass}>
                <div className="flex items-center gap-2">
                    <span className="font-semibold">{account.display_name}</span>
                    {isConnected && account.account_identifier ? (
                        <span className="truncate text-sm text-secondary">· {account.account_identifier}</span>
                    ) : null}
                </div>
                <div className="mt-0.5 text-xs text-secondary">
                    {!isConnected
                        ? 'Not connected'
                        : account.created_at
                          ? `Linked ${humanFriendlyDetailedTime(account.created_at)}`
                          : 'Linked'}
                </div>
                {account.provider === 'github' ? (
                    <div className="mt-1 text-xs text-secondary italic text-balance">
                        Besides login, connecting GitHub lets PostHog attribute Inbox reports, assign Error Tracking
                        issues, and open PostHog Code pull requests on your behalf.
                    </div>
                ) : null}
            </div>
            <div className="flex shrink-0 items-center gap-3">
                <StatusTag account={account} />
                {isConnected && account.provider === 'github' ? (
                    <GithubSignInToggle
                        account={account}
                        onChange={(value) => onSetLoginEnabled(account.provider, value)}
                    />
                ) : null}
                {!isConnected ? (
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => onConnect(account)}
                        disabledReason={!account.connect_path ? 'Connecting this provider is not available' : undefined}
                    >
                        Connect
                    </LemonButton>
                ) : (
                    <LemonButton
                        type="tertiary"
                        status="danger"
                        size="small"
                        disabledReason={
                            !account.can_disconnect
                                ? 'Required by your organization and cannot be disconnected.'
                                : undefined
                        }
                        onClick={() => onDisconnect(account)}
                    >
                        Disconnect
                    </LemonButton>
                )}
            </div>
        </div>
    )
}

export function LinkedAccounts(): JSX.Element {
    const { linkedAccounts, linkedAccountsLoading, ssoEnforcementProviderName } = useValues(linkedAccountsLogic)
    const { setLoginEnabled, disconnect, connect } = useActions(linkedAccountsLogic)

    const handleDisconnect = (account: LinkedAccount): void => {
        LemonDialog.open({
            title: `Disconnect ${account.display_name}?`,
            description:
                account.provider === 'github'
                    ? 'PostHog will no longer be able to attribute code changes to your PostHog account. You can re-link anytime.'
                    : `You'll no longer be able to sign in with ${account.display_name}. You can re-link anytime.`,
            primaryButton: {
                children: 'Disconnect',
                status: 'danger',
                onClick: () => disconnect(account.provider, account.display_name),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    if (linkedAccountsLoading && linkedAccounts.length === 0) {
        return (
            <div className="deprecated-space-y-2">
                <LemonSkeleton className="h-16 w-full" />
                <LemonSkeleton className="h-16 w-full" />
            </div>
        )
    }

    if (linkedAccounts.length === 0) {
        return (
            <div className="rounded border border-dashed px-4 py-6 text-center text-sm text-secondary">
                No sign-in providers are configured on this PostHog instance.
            </div>
        )
    }

    return (
        <div className="deprecated-space-y-3">
            {ssoEnforcementProviderName ? (
                <LemonBanner type="info">
                    Your organization requires signing in with <b>{ssoEnforcementProviderName}</b>. Other sign-in
                    methods are disabled for your account.
                </LemonBanner>
            ) : null}
            <div className="divide-y rounded border bg-surface-primary">
                {linkedAccounts.map((account) => (
                    <LinkedAccountRow
                        key={account.provider}
                        account={account}
                        onSetLoginEnabled={setLoginEnabled}
                        onDisconnect={handleDisconnect}
                        onConnect={connect}
                    />
                ))}
            </div>
        </div>
    )
}
