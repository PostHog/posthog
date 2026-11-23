import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { GitHubInstallRequestItemApi } from '~/generated/core/api.schemas'

export function QuillGitHubInstallRequestsBanner({
    pendingInstallRequests,
    approvedInstallRequests,
    installUrl,
    orgOwnerMessage,
    dismissingRequestIds,
    onDismiss,
    onCopyOrgOwnerMessage,
    onFinishConnecting,
    finishConnectingUrl,
    variant,
    connecting,
}: {
    pendingInstallRequests: GitHubInstallRequestItemApi[]
    approvedInstallRequests: GitHubInstallRequestItemApi[]
    installUrl: string | null
    orgOwnerMessage: string | null
    dismissingRequestIds: string[]
    onDismiss: (id: string) => void
    onCopyOrgOwnerMessage: (url: string) => void
    onFinishConnecting?: () => void
    finishConnectingUrl?: string
    variant: 'default' | 'onboarding'
    connecting: boolean
}): JSX.Element {
    const dismissButton = (request: GitHubInstallRequestItemApi): JSX.Element => (
        <Button loading={dismissingRequestIds.includes(request.id)} onClick={() => onDismiss(request.id)}>
            Dismiss
        </Button>
    )

    return (
        <div className="flex w-full flex-col gap-2">
            {approvedInstallRequests.map((request) => (
                <Item key={request.id} tone="success" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            An organization owner approved the PostHog app for{' '}
                            <strong>{request.account_login || request.github_login || 'your organization'}</strong>.
                            Finish connecting to start using it.
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions className="flex-wrap">
                        <Button
                            variant="primary"
                            nativeButton={!finishConnectingUrl}
                            render={
                                finishConnectingUrl ? (
                                    <LinkPrimitive to={finishConnectingUrl} disableClientSideRouting />
                                ) : undefined
                            }
                            onClick={onFinishConnecting}
                            loading={connecting}
                        >
                            Finish connecting
                        </Button>
                        {variant === 'default' ? dismissButton(request) : null}
                    </ItemActions>
                </Item>
            ))}
            {pendingInstallRequests.map((request) => (
                <Item key={request.id} tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            GitHub sent your request
                            {request.github_login ? (
                                <>
                                    {' '}
                                    (as <strong>{request.github_login}</strong>)
                                </>
                            ) : null}{' '}
                            to your organization owners. Once an owner approves the PostHog app, we'll finish connecting
                            here.
                            {variant === 'onboarding' && installUrl ? (
                                <>
                                    {' '}
                                    <Button
                                        variant="link"
                                        size="inline"
                                        nativeButton={false}
                                        render={<LinkPrimitive to={installUrl} target="_blank" />}
                                    >
                                        Open the approval page
                                    </Button>
                                    .
                                </>
                            ) : null}
                        </ItemDescription>
                        {variant === 'default' && orgOwnerMessage ? (
                            <ItemDescription>
                                <code className="break-words whitespace-normal">{orgOwnerMessage}</code>
                            </ItemDescription>
                        ) : null}
                    </ItemContent>
                    {variant === 'default' ? (
                        <ItemActions className="flex-wrap">
                            {installUrl ? (
                                <Button variant="outline" onClick={() => onCopyOrgOwnerMessage(installUrl)}>
                                    Copy message for your org owner
                                </Button>
                            ) : null}
                            {dismissButton(request)}
                        </ItemActions>
                    ) : null}
                </Item>
            ))}
        </div>
    )
}
