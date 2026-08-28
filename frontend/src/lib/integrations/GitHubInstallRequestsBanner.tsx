import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { githubInstallRequestsLogic } from 'lib/integrations/githubInstallRequestsLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import type { GitHubInstallRequestItemApi } from '~/generated/core/api.schemas'

export function buildOrgOwnerMessage(installUrl: string): string {
    return `Can you approve the PostHog GitHub app for our organization? Open ${installUrl}, pick the organization, and approve the pending request.`
}

/**
 * Surfaces the "waiting for a GitHub org owner" state and its resolution. Rendering this
 * subscribes the surface to install-request polling for as long as it stays mounted.
 */
export function GitHubInstallRequestsBanner({
    onFinishConnecting,
    finishConnectingUrl,
}: {
    /** Runs the surface's own connect flow once an owner has approved the install. */
    onFinishConnecting?: () => void
    /** Alternative to `onFinishConnecting` for surfaces whose connect is a plain link. */
    finishConnectingUrl?: string
}): JSX.Element | null {
    const { pendingInstallRequests, approvedInstallRequests, installUrl, dismissingRequestIds } =
        useValues(githubInstallRequestsLogic)
    const { startPolling, stopPolling, dismissInstallRequest } = useActions(githubInstallRequestsLogic)

    useOnMountEffect(() => {
        startPolling()
        return () => stopPolling()
    })

    if (pendingInstallRequests.length === 0 && approvedInstallRequests.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            {approvedInstallRequests.map((request: GitHubInstallRequestItemApi) => (
                <LemonBanner key={request.id} type="success" hideIcon>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-sm font-normal">
                            An organization owner approved the PostHog app for{' '}
                            <strong>{request.account_login || request.github_login || 'your organization'}</strong>.
                            Finish connecting to start using it.
                        </span>
                        <div className="flex gap-2 shrink-0">
                            <LemonButton
                                type="primary"
                                size="small"
                                to={finishConnectingUrl}
                                disableClientSideRouting={!!finishConnectingUrl}
                                onClick={onFinishConnecting}
                            >
                                Finish connecting
                            </LemonButton>
                            <LemonButton
                                type="tertiary"
                                size="small"
                                loading={dismissingRequestIds.includes(request.id)}
                                onClick={() => dismissInstallRequest(request.id)}
                            >
                                Dismiss
                            </LemonButton>
                        </div>
                    </div>
                </LemonBanner>
            ))}
            {pendingInstallRequests.map((request: GitHubInstallRequestItemApi) => (
                <LemonBanner key={request.id} type="info" hideIcon>
                    <div className="flex flex-col gap-2">
                        <span className="text-sm font-normal">
                            GitHub sent your request
                            {request.github_login ? (
                                <>
                                    {' '}
                                    (as <strong>{request.github_login}</strong>)
                                </>
                            ) : null}{' '}
                            to your organization owners. Once an owner approves the PostHog app, we'll finish connecting
                            here.
                        </span>
                        {installUrl ? (
                            <code className="text-xs whitespace-normal break-words">
                                {buildOrgOwnerMessage(installUrl)}
                            </code>
                        ) : null}
                        <div className="flex flex-wrap gap-2">
                            {installUrl ? (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={() =>
                                        void copyToClipboard(
                                            buildOrgOwnerMessage(installUrl),
                                            'message for your org owner'
                                        )
                                    }
                                >
                                    Copy message for your org owner
                                </LemonButton>
                            ) : null}
                            <LemonButton
                                type="tertiary"
                                size="small"
                                loading={dismissingRequestIds.includes(request.id)}
                                onClick={() => dismissInstallRequest(request.id)}
                            >
                                Dismiss
                            </LemonButton>
                        </div>
                    </div>
                </LemonBanner>
            ))}
        </div>
    )
}
