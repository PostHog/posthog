import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSkeleton } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils'

import { linkedAccountsLogic } from './linkedAccountsLogic'

export function LinkedAccounts(): JSX.Element {
    const { linkedAccounts, linkedAccountsLoading } = useValues(linkedAccountsLogic)
    const { disconnectGitHub, connectGitHub } = useActions(linkedAccountsLogic)

    const github = linkedAccounts.find((a) => a.kind === 'github')

    const handleDisconnect = (): void => {
        LemonDialog.open({
            title: 'Disconnect GitHub?',
            description:
                'PostHog will no longer be able to access your repos or attribute code changes to your PostHog account. You can reconnect anytime.',
            primaryButton: {
                children: 'Disconnect',
                status: 'danger',
                onClick: () => disconnectGitHub(),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    if (linkedAccountsLoading && linkedAccounts.length === 0) {
        return (
            <div className="deprecated-space-y-2">
                <LemonSkeleton className="h-16 w-full" />
            </div>
        )
    }

    return (
        <div className="deprecated-space-y-3">
            <div className="divide-y rounded border bg-surface-primary">
                <div className="flex items-center gap-4 px-4 py-3">
                    <div className={`shrink-0${github?.connected ? '' : ' opacity-60'}`}>
                        <div className="flex h-10 w-10 items-center justify-center rounded-md border bg-surface-secondary text-2xl">
                            <IconGithub />
                        </div>
                    </div>
                    <div className={`min-w-0 flex-1${github?.connected ? '' : ' opacity-60'}`}>
                        <div className="flex items-center gap-2">
                            <span className="font-semibold">GitHub</span>
                            {github?.connected && github.account_identifier ? (
                                <span className="truncate text-sm text-secondary">· {github.account_identifier}</span>
                            ) : null}
                        </div>
                        <div className="mt-0.5 text-xs text-secondary">
                            {!github?.connected
                                ? 'Not connected'
                                : github.created_at
                                  ? `Connected ${humanFriendlyDetailedTime(github.created_at)}`
                                  : 'Connected'}
                            {github?.connected && github.account ? ` · ${github.account.name}` : null}
                        </div>
                        <div className="mt-1 text-xs text-secondary italic text-balance">
                            Connecting GitHub lets PostHog access your repos, attribute Inbox reports, assign Error
                            Tracking issues, and open PostHog Code pull requests on your behalf.
                        </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                        {!github?.connected ? (
                            <LemonButton type="primary" size="small" onClick={connectGitHub}>
                                Connect
                            </LemonButton>
                        ) : (
                            <LemonButton type="tertiary" status="danger" size="small" onClick={handleDisconnect}>
                                Disconnect
                            </LemonButton>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
