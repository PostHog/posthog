import { useActions, useValues } from 'kea'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { JSSnippet } from 'lib/components/JSSnippet'
import { JSBookmarklet } from 'lib/components/JSBookmarklet'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { AutocaptureSettings } from './AutocaptureSettings'

export function IngestionInfo({ loadingComponent }: { loadingComponent: JSX.Element }): JSX.Element {
    const { currentTeam, currentTeamLoading, isTeamTokenResetAvailable } = useValues(teamLogic)
    const { resetToken } = useActions(teamLogic)

    if (currentTeam?.is_demo) {
        return (
            <>
                <h2 id="snippet" className="subtitle">
                    Event ingestion
                </h2>
                <p>
                    PostHog can ingest events from almost anywhere - JavaScript, Android, iOS, React Native, Node.js,
                    Ruby, Go, and more.
                </p>
                <p>
                    Demo projects like this one can't ingest events, but you can{' '}
                    <Link to="https://posthog.com/docs/integrations" target="_blank">
                        read about ingestion in our Docs
                    </Link>{' '}
                    and use a non-demo project to ingest your own events.
                </p>
            </>
        )
    }

    return (
        <>
            <h2 id="snippet" className="subtitle">
                Web snippet
            </h2>
            <p>
                PostHog's configurable web snippet allows you to (optionally) autocapture events, record user sessions,
                and more with no extra work. Place the following snippet in your website's HTML, ideally just above the{' '}
                <code>{'</head>'}</code> tag.
            </p>
            <p>
                For more guidance, including on identifying users,{' '}
                <Link to="https://posthog.com/docs/integrations/js-integration">see PostHog Docs</Link>.
            </p>
            {currentTeamLoading && !currentTeam ? loadingComponent : <JSSnippet />}
            <LemonDivider className="my-6" />
            <AutocaptureSettings />
            <LemonDivider className="my-6" />
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
