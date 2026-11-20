import { IconGithub } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, Text, cn } from '@posthog/quill'

import { GitHubInstallRequestsBanner } from 'lib/integrations/GitHubInstallRequestsBanner'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { GitHubAvailableInstallationApi } from 'products/integrations/frontend/generated/api.schemas'

import { accountLabel, sourceLabel } from './githubInstallationLabels'
import { Integration } from './Integration'
import { QuillGitHubInstallationLink } from './QuillGitHubInstallationLink'

export function QuillGithubIntegration({
    centered,
    integrationSuffix,
    authorizationUrl,
    authorizing,
    emphasizeConnect,
    connectText,
    connectDescription,
    isConnected,
    canLinkExisting,
    installations,
    personalGithubLogin,
    linkingInstallation,
    projectName,
    lookingForInstallations,
    personalDiscoveryFailed,
    hideConnect,
    showManageHint,
    showPersonalHelp,
    onFinishConnecting,
    onPickerVisibilityChange,
    onLinkInstallation,
    onRetryDiscovery,
    onConnect,
    onConnectOrManage,
}: {
    centered: boolean
    integrationSuffix?: JSX.Element
    /** Undefined when the surface runs its own connect flow through `onConnect`. */
    authorizationUrl: string | undefined
    authorizing: boolean
    emphasizeConnect: boolean
    connectText: string
    connectDescription?: React.ReactNode
    isConnected: boolean
    canLinkExisting: boolean
    installations: GitHubAvailableInstallationApi[]
    personalGithubLogin?: string | null
    linkingInstallation: boolean
    projectName?: string
    lookingForInstallations: boolean
    personalDiscoveryFailed: boolean
    hideConnect: boolean
    showManageHint: boolean
    showPersonalHelp: boolean
    onFinishConnecting: () => void
    onPickerVisibilityChange: (visible: boolean) => void
    onLinkInstallation: (installationId?: string) => void
    onRetryDiscovery: () => void
    onConnect: () => void
    onConnectOrManage: () => void
}): JSX.Element {
    const authorizeLink = authorizationUrl ? (
        <LinkPrimitive to={authorizationUrl} disableClientSideRouting />
    ) : undefined

    return (
        <Integration kind="github" centered={centered} integrationSuffix={integrationSuffix}>
            <div className="flex w-full flex-col gap-2">
                <GitHubInstallRequestsBanner
                    finishConnectingUrl={authorizationUrl}
                    connecting={authorizing}
                    onFinishConnecting={onFinishConnecting}
                    variant={emphasizeConnect ? 'onboarding' : 'default'}
                />

                {canLinkExisting && (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                {installations.length > 1 ? (
                                    <span>PostHog is already installed on more than one GitHub account.</span>
                                ) : installations[0].source_team_id !== null ? (
                                    <span>
                                        PostHog is installed on <strong>{accountLabel(installations[0])}</strong> and
                                        connected to{' '}
                                        <strong>
                                            {installations[0].source_team_name ??
                                                `project ${installations[0].source_team_id}`}
                                        </strong>
                                        .
                                    </span>
                                ) : (
                                    <span>
                                        PostHog is installed on the GitHub account{' '}
                                        <strong>{accountLabel(installations[0])}</strong>.{' '}
                                        <span>{sourceLabel(installations[0], personalGithubLogin)}.</span>
                                    </span>
                                )}
                            </ItemDescription>
                            {installations.some((installation) => installation.source_team_id === null) && (
                                <ItemDescription>
                                    GitHub can include accounts whose repositories you can access.
                                </ItemDescription>
                            )}
                        </ItemContent>
                        <ItemActions>
                            <QuillGitHubInstallationLink
                                onVisibilityChange={onPickerVisibilityChange}
                                personalGithubLogin={personalGithubLogin}
                                installations={installations}
                                loading={linkingInstallation}
                                emphasizeInstallation={emphasizeConnect}
                                onLink={onLinkInstallation}
                                projectName={projectName}
                            />
                        </ItemActions>
                    </Item>
                )}

                {lookingForInstallations && (
                    <span role="status" className="sr-only">
                        Looking for existing GitHub installations…
                    </span>
                )}

                {personalDiscoveryFailed && (
                    <Item tone="warning" size="sm">
                        <ItemContent>
                            <ItemDescription>Couldn't check your personal GitHub connection.</ItemDescription>
                        </ItemContent>
                        <ItemActions>
                            <Button onClick={onRetryDiscovery}>Retry</Button>
                        </ItemActions>
                    </Item>
                )}

                {hideConnect ? null : emphasizeConnect && !isConnected ? (
                    <div className={cn('flex w-full flex-col gap-2', centered ? 'items-center' : 'items-start')}>
                        <Button
                            variant={canLinkExisting ? 'outline' : 'primary'}
                            render={authorizeLink}
                            loading={authorizing}
                            onClick={onConnect}
                        >
                            <IconGithub />
                            {canLinkExisting ? 'Connect a different organization or repository' : connectText}
                        </Button>
                        {connectDescription !== '' && (
                            <Text size="xs" variant="muted" render={<p className="m-0 max-w-130 text-center" />}>
                                {connectDescription ?? (
                                    <>
                                        PostHog uses GitHub to create reports and pull requests based on your code.
                                        After connecting GitHub, you can run Wizard in the background to complete setup.
                                    </>
                                )}
                            </Text>
                        )}
                    </div>
                ) : (
                    <div className={cn('flex flex-wrap gap-2', centered && 'justify-center')}>
                        <Button
                            variant="outline"
                            render={authorizeLink}
                            loading={authorizing}
                            onClick={onConnectOrManage}
                        >
                            {isConnected ? 'Manage on GitHub' : connectText}
                        </Button>
                    </div>
                )}

                {showManageHint && (
                    <Text size="xs" variant="muted" render={<p className={cn('m-0', centered && 'text-center')} />}>
                        Add the PostHog app to another GitHub account, or change which repositories it can see.
                    </Text>
                )}

                {showPersonalHelp && (
                    <Text size="xs" variant="muted" render={<p className={cn('m-0', centered && 'text-center')} />}>
                        Already installed the PostHog GitHub App but don't see it here? Connect your GitHub account
                        under{' '}
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.settings('user-personal-integrations')} />}
                        >
                            Personal integrations
                        </Button>{' '}
                        so PostHog can find it.
                    </Text>
                )}
            </div>
        </Integration>
    )
}
