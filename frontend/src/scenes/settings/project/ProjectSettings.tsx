import { useActions, useValues } from 'kea'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { JSSnippet } from 'lib/components/JSSnippet'
import { JSBookmarklet } from 'lib/components/JSBookmarklet'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { LemonButton, LemonInput, LemonLabel, LemonSkeleton } from '@posthog/lemon-ui'
import { useState } from 'react'
import { TimezoneConfig } from './TimezoneConfig'
import { WeekStartConfig } from './WeekStartConfig'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { urls } from '@posthog/apps-common'

export function ProjectDisplayName(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const [name, setName] = useState(currentTeam?.name || '')

    if (currentTeam?.is_demo) {
        return (
            <p>
                <i>The demo project cannot be renamed.</i>
            </p>
        )
    }

    return (
        <div className="space-y-4" style={{ maxWidth: '40rem' }}>
            <LemonInput value={name} onChange={setName} disabled={currentTeamLoading} />
            <LemonButton
                type="primary"
                onClick={() => updateCurrentTeam({ name })}
                disabled={!name || !currentTeam || name === currentTeam.name}
                loading={currentTeamLoading}
            >
                Rename Project
            </LemonButton>
        </div>
    )
}

export function WebSnippet(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return (
        <>
            <p>
                PostHog's configurable web snippet allows you to (optionally) autocapture events, record user sessions,
                and more with no extra work. Place the following snippet in your website's HTML, ideally just above the{' '}
                <code>{'</head>'}</code> tag.
            </p>
            <p>
                For more guidance, including on identifying users,{' '}
                <Link to="https://posthog.com/docs/integrations/js-integration">see PostHog Docs</Link>.
            </p>
            {currentTeamLoading && !currentTeam ? (
                <div className="space-y-4">
                    <LemonSkeleton className="w-1/2" />
                    <LemonSkeleton repeat={3} />
                </div>
            ) : (
                <JSSnippet />
            )}
        </>
    )
}

export function Misc(): JSX.Element {
    const { currentTeam, isTeamTokenResetAvailable } = useValues(teamLogic)
    const { resetToken } = useActions(teamLogic)

    return (
        <>
            <p>Need to test PostHog on a live site without changing any code?</p>
            <p>
                Just drag the bookmarklet below to your bookmarks bar, open the website you want to test PostHog on and
                click it. This will enable our tracking, on the currently loaded page only. The data will show up in
                this project.
            </p>
            <div>{isAuthenticatedTeam(currentTeam) && <JSBookmarklet team={currentTeam} />}</div>
            <LemonDivider className="my-6" />
            <h2 id="custom-events" className="subtitle">
                Send custom events
            </h2>
            To send custom events <Link to="https://posthog.com/docs/integrations">visit PostHog Docs</Link> and
            integrate the library for the specific language or platform you're using. We support Python, Ruby, Node, Go,
            PHP, iOS, Android, and more.
            <LemonDivider className="my-6" />
            <h2 id="project-variables" className="subtitle mb-4">
                Project Variables
            </h2>
            <h3 id="project-api-key" className="l3">
                Project API Key
            </h3>
            <p>
                You can use this write-only key in any one of{' '}
                <Link to="https://posthog.com/docs/integrations">our libraries</Link>.
            </p>
            <CodeSnippet
                actions={
                    isTeamTokenResetAvailable
                        ? [
                              {
                                  icon: <IconRefresh />,
                                  title: 'Reset project API key',
                                  popconfirmProps: {
                                      title: (
                                          <>
                                              Reset the project's API key?{' '}
                                              <b>This will invalidate the current API key and cannot be undone.</b>
                                          </>
                                      ),
                                      okText: 'Reset key',
                                      okType: 'danger',
                                      placement: 'left',
                                  },
                                  callback: resetToken,
                              },
                          ]
                        : []
                }
                thing="project API key"
            >
                {currentTeam?.api_token || ''}
            </CodeSnippet>
            <p>
                Write-only means it can only create new events. It can't read events or any of your other data stored
                with PostHog, so it's safe to use in public apps.
            </p>
            <h3 id="project-id" className="l3 mt-4">
                Project ID
            </h3>
            <p>
                You can use this ID to reference your project in our <Link to="https://posthog.com/docs/api">API</Link>.
            </p>
            <CodeSnippet thing="project ID">{String(currentTeam?.id || '')}</CodeSnippet>
        </>
    )
}

export function Bookmarklet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <p>Need to test PostHog on a live site without changing any code?</p>
            <p>
                Just drag the bookmarklet below to your bookmarks bar, open the website you want to test PostHog on and
                click it. This will enable our tracking, on the currently loaded page only. The data will show up in
                this project.
            </p>
            <div>{isAuthenticatedTeam(currentTeam) && <JSBookmarklet team={currentTeam} />}</div>
        </>
    )
}

export function ProjectVariables(): JSX.Element {
    const { currentTeam, isTeamTokenResetAvailable } = useValues(teamLogic)
    const { resetToken } = useActions(teamLogic)

    return (
        <div className="flex items-start gap-4 flex-wrap">
            {/* <h2 id="custom-events" className="subtitle">
                Send custom events
            </h2>
            To send custom events <Link to="https://posthog.com/docs/integrations">visit PostHog Docs</Link> and
            integrate the library for the specific language or platform you're using. We support Python, Ruby, Node, Go,
            PHP, iOS, Android, and more. */}
            <div className="flex-1">
                <h3 id="project-api-key" className="min-w-100">
                    Project API Key
                </h3>
                <p>
                    You can use this write-only key in any one of{' '}
                    <Link to="https://posthog.com/docs/integrations">our libraries</Link>.
                </p>
                <CodeSnippet
                    actions={
                        isTeamTokenResetAvailable
                            ? [
                                  {
                                      icon: <IconRefresh />,
                                      title: 'Reset project API key',
                                      popconfirmProps: {
                                          title: (
                                              <>
                                                  Reset the project's API key?{' '}
                                                  <b>This will invalidate the current API key and cannot be undone.</b>
                                              </>
                                          ),
                                          okText: 'Reset key',
                                          okType: 'danger',
                                          placement: 'left',
                                      },
                                      callback: resetToken,
                                  },
                              ]
                            : []
                    }
                    thing="project API key"
                >
                    {currentTeam?.api_token || ''}
                </CodeSnippet>
                <p>
                    Write-only means it can only create new events. It can't read events or any of your other data
                    stored with PostHog, so it's safe to use in public apps.
                </p>
            </div>
            <div className="flex-1">
                <h3 id="project-id" className="min-w-100">
                    Project ID
                </h3>
                <p>
                    You can use this ID to reference your project in our{' '}
                    <Link to="https://posthog.com/docs/api">API</Link>.
                </p>
                <CodeSnippet thing="project ID">{String(currentTeam?.id || '')}</CodeSnippet>
            </div>
        </div>
    )
}

export function ProjectTimezone(): JSX.Element {
    return (
        <>
            <p>
                These settings affect how PostHog displays, buckets, and filters time-series data. You may need to
                refresh insights for new settings to apply.
            </p>
            <div className="space-y-2">
                <LemonLabel id="timezone">Time zone</LemonLabel>
                <TimezoneConfig />
                <LemonLabel id="timezone">Week starts on</LemonLabel>
                <WeekStartConfig />
            </div>
        </>
    )
}

export function ProjectToolbarURLs(): JSX.Element {
    return (
        <>
            <p>
                These are the URLs where the{' '}
                <b>
                    <Link to={urls.toolbarLaunch()}>Toolbar</Link> will automatically launch
                </b>{' '}
                (if you're logged in).
            </p>
            <p>
                <b>Domains and wildcard subdomains are allowed</b> (example: <code>https://*.example.com</code>).
                However, wildcarded top-level domains cannot be used (for security reasons).
            </p>
            <AuthorizedUrlList type={AuthorizedUrlListType.TOOLBAR_URLS} />
        </>
    )
}
