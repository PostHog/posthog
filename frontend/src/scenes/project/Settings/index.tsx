import React, { useState } from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import { IPCapture } from './IPCapture'
import { JSSnippet } from 'lib/components/JSSnippet'
import { SessionRecording } from './SessionRecording'
import { WebhookIntegration } from './WebhookIntegration'
import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { ToolbarSettings } from './ToolbarSettings'
import { CodeSnippet } from 'scenes/ingestion/frameworks/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'
import { DangerZone } from './DangerZone'
import { PageHeader } from 'lib/components/PageHeader'
import { Link } from 'lib/components/Link'
import { JSBookmarklet } from 'lib/components/JSBookmarklet'
import { RestrictedArea, RestrictionScope } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { TestAccountFiltersConfig } from './TestAccountFiltersConfig'
import { TimezoneConfig } from './TimezoneConfig'
import { DataAttributes } from 'scenes/project/Settings/DataAttributes'
import { AvailableFeature, InsightType } from '~/types'
import { TeamMembers } from './TeamMembers'
import { teamMembersLogic } from './teamMembersLogic'
import { AccessControl } from './AccessControl'
import { PathCleaningFiltersConfig } from './PathCleaningFiltersConfig'
import { userLogic } from 'scenes/userLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { CorrelationConfig } from './CorrelationConfig'
import { urls } from 'scenes/urls'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { GroupAnalytics } from 'scenes/project/Settings/GroupAnalytics'
import { IconInfo, IconRefresh } from 'lib/components/icons'
import { PersonDisplayNameProperties } from './PersonDisplayNameProperties'
import { Tooltip } from 'lib/components/Tooltip'
import { SlackIntegration } from './SlackIntegration'
import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'

export const scene: SceneExport = {
    component: ProjectSettings,
}

function DisplayName(): JSX.Element {
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

export function ProjectSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading, isTeamTokenResetAvailable } = useValues(teamLogic)
    const { resetToken } = useActions(teamLogic)
    const { location } = useValues(router)
    const { user, hasAvailableFeature } = useValues(userLogic)
    const hasAdvancedPaths = user?.organization?.available_features?.includes(AvailableFeature.PATHS_ADVANCED)

    useAnchor(location.hash)

    const loadingComponent = (
        <div className="space-y-4">
            <LemonSkeleton className="w-1/2" />
            <LemonSkeleton repeat={3} />
        </div>
    )

    return (
        <div>
            <PageHeader
                title="Project settings"
                caption={`Organize your analytics within the project. These settings only apply to ${
                    currentTeam?.name ?? 'the current project'
                }.`}
            />
            <div className="border rounded p-6">
                <h2 id="name" className="subtitle mt-0">
                    Display name
                </h2>
                {currentTeamLoading && !currentTeam ? loadingComponent : <DisplayName />}
                <LemonDivider className="my-6" />
                <h2 id="snippet" className="subtitle">
                    Website event autocapture
                </h2>
                To integrate PostHog into your website and get event autocapture with no additional work, include the
                following snippet in your&nbsp;website's&nbsp;HTML. Ideally, put it just above the&nbsp;
                <code>{'</head>'}</code>&nbsp;tag.
                <br />
                For more guidance, including on identifying users,{' '}
                <a href="https://posthog.com/docs/integrations/js-integration">see PostHog Docs</a>.
                {currentTeamLoading && !currentTeam ? loadingComponent : <JSSnippet />}
                <p>
                    You can even test PostHog out on a live site without changing any code.
                    <br />
                    Just drag the bookmarklet below to your bookmarks bar, open the website you want to test PostHog on
                    and click it.
                    <br />
                    This will enable our tracking, on the currently loaded page only. The data will show up in this
                    project.
                    <br />
                </p>
                <div>{currentTeam && <JSBookmarklet team={currentTeam} />}</div>
                <LemonDivider className="my-6" />
                <h2 id="custom-events" className="subtitle">
                    Send custom events
                </h2>
                To send custom events <a href="https://posthog.com/docs/integrations">visit PostHog Docs</a> and
                integrate the library for the specific language or platform you're using. We support Python, Ruby, Node,
                Go, PHP, iOS, Android, and more.
                <LemonDivider className="my-6" />
                <h2 id="project-variables" className="subtitle mb-4">
                    Project Variables
                </h2>
                <h3 id="project-api-key" className="l3">
                    Project API Key
                </h3>
                <p>
                    You can use this write-only key in any one of{' '}
                    <a href="https://posthog.com/docs/integrations">our libraries</a>.
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
                    copyDescription="project API key"
                >
                    {currentTeam?.api_token || ''}
                </CodeSnippet>
                <p>
                    Write-only means it can only create new events. It can't read events or any of your other data
                    stored with PostHog, so it's safe to use in public apps.
                </p>
                <h3 id="project-id" className="l3 mt-4">
                    Project ID
                </h3>
                <p>
                    You can use this ID to reference your project in our <a href="https://posthog.com/docs/api">API</a>.
                </p>
                <CodeSnippet copyDescription="project ID">{String(currentTeam?.id || '')}</CodeSnippet>
                <LemonDivider className="my-6" />
                <h2 className="subtitle" id="timezone">
                    Timezone
                </h2>
                <p>
                    Set the timezone for your project. All charts will be based on this timezone, including how PostHog
                    buckets data in day/week/month intervals.
                </p>
                <div style={{ maxWidth: '40rem' }}>
                    <TimezoneConfig />
                </div>
                <LemonDivider className="my-6" />
                <h2 className="subtitle" id="internal-users-filtering">
                    Filter out internal and test users{' '}
                    <Tooltip title='Events will still be ingested and saved, but they will be excluded from any queries where the "Filter out internal and test users" toggle is set.'>
                        <IconInfo style={{ fontSize: '1em', color: 'var(--muted-alt)', marginTop: 4, marginLeft: 5 }} />
                    </Tooltip>
                </h2>
                <p>
                    Increase the quality of your analytics results by filtering out events from internal sources, such
                    as team members, test accounts, or development environments.{' '}
                    <strong>
                        The filters you apply here are added as extra filters when the toggle is switched on.
                    </strong>{' '}
                    So, if you apply a cohort, it means you will only match users in that cohort.
                </p>
                <strong>Example filters</strong>
                <ul className="list-disc pl-4 mb-2">
                    <li>
                        "<strong>Email</strong> does not contain <strong>yourcompany.com</strong>" to exclude all events
                        from your company's team members.
                    </li>
                    <li>
                        "<strong>Host</strong> does not contain <strong>localhost</strong>" to exclude all events from
                        local development environments.
                    </li>
                </ul>
                <TestAccountFiltersConfig />
                <LemonDivider className="my-6" />
                <CorrelationConfig />
                {hasAdvancedPaths && (
                    <>
                        <LemonDivider className="my-6" />
                        <h2 className="subtitle" id="path_cleaning_filtering">
                            Path cleaning rules
                            <LemonTag type="warning" style={{ marginLeft: 8 }}>
                                Beta
                            </LemonTag>
                        </h2>
                        <p>
                            Make your <Link to={urls.insightNew({ insight: InsightType.PATHS })}>Paths</Link> clearer by
                            aliasing one or multiple URLs.{' '}
                            <i>
                                Example: <code>htttp://client1.mydomain.com/accounts</code> and{' '}
                                <code>htttp://tenant2.mydomain.com/accounts</code> can become a single{' '}
                                <code>accounts</code> path.
                            </i>
                        </p>
                        <p>
                            Each rule is composed of an alias and a regex pattern. Any pattern in a URL or event name
                            that matches the regex will be replaced with the alias. Rules are applied in the order that
                            they're listed.
                        </p>
                        <p>
                            <b>
                                Rules that you set here will be applied before wildcarding and other regex replacement
                                if the toggle is switched on.
                            </b>
                        </p>
                        <PathCleaningFiltersConfig />
                    </>
                )}
                <LemonDivider className="my-6" />
                <div id="permitted-domains" /> {/** DEPRECATED: Remove after Jun 1, 2022 */}
                <div id="authorized-urls" />
                <h2 className="subtitle" id="urls">
                    Authorized URLs
                </h2>
                <p>
                    These are the URLs where the{' '}
                    <b>
                        <Link to={urls.toolbarLaunch()}>Toolbar</Link> will automatically launch
                    </b>{' '}
                    (if you're logged in) and where we'll <b>record sessions</b> (if <a href="#recordings">enabled</a>).
                </p>
                <p>
                    <b>Domains and wilcard subdomains are allowed</b> (example: <code>https://*.example.com</code>).
                    However, wildcarded top-level domains cannot be used (for security reasons).
                </p>
                <AuthorizedUrlList type={AuthorizedUrlListType.TOOLBAR_URLS} />
                <LemonDivider className="my-6" />
                <h2 className="subtitle" id="attributes">
                    Data attributes
                </h2>
                <DataAttributes />
                <LemonDivider className="my-6" />
                <h2 className="subtitle" id="person-display-name">
                    Person Display Name
                </h2>
                <PersonDisplayNameProperties />
                <LemonDivider className="my-6" />
                <h2 className="subtitle" id="webhook">
                    Webhook integration
                </h2>
                <WebhookIntegration />
                <LemonDivider className="my-6" />
                <>
                    <h2 className="subtitle" id="slack">
                        Slack integration
                    </h2>
                    <SlackIntegration />
                    <LemonDivider className="my-6" />
                </>
                <h2 className="subtitle" id="datacapture">
                    Data capture configuration
                </h2>
                <IPCapture />
                <LemonDivider className="my-6" />
                <h2 className="subtitle">PostHog Toolbar</h2>
                <p>
                    Enable PostHog Toolbar, which gives access to heatmaps, stats and allows you to create actions,
                    right there on your website!
                </p>
                <ToolbarSettings />
                <LemonDivider className="my-6" />
                <h2 id="recordings" className="subtitle">
                    Recordings
                </h2>
                <p>
                    Watch recordings of how users interact with your web app to see what can be improved. Recordings are
                    found in the <Link to={urls.sessionRecordings()}>recordings page</Link>.
                </p>
                <p>
                    Please note <b>your website needs to have</b> the <a href="#snippet">PostHog snippet</a> or the
                    latest version of{' '}
                    <a
                        href="https://posthog.com/docs/integrations/js-integration?utm_campaign=session-recording&utm_medium=in-product"
                        target="_blank"
                    >
                        posthog-js
                    </a>{' '}
                    <b>directly</b> installed. For more details, check out our{' '}
                    <a
                        href="https://posthog.com/docs/user-guides/recordings?utm_campaign=session-recording&utm_medium=in-product"
                        target="_blank"
                    >
                        docs
                    </a>
                    .
                </p>
                <SessionRecording />
                {currentTeam?.session_recording_opt_in ? (
                    <>
                        <h2 className="subtitle my-6" id="urls">
                            Authorized domains for recordings
                        </h2>
                        <p>
                            Use the settings below to restrict the domains where recordings will be captured. If no
                            domains are selected, then there will be no domain restriction.
                        </p>
                        <p>
                            <b>Domains and wilcard subdomains are allowed</b> (example:{' '}
                            <code>https://*.example.com</code>). However, wildcarded top-level domains cannot be used
                            (for security reasons).
                        </p>
                        <AuthorizedUrlList type={AuthorizedUrlListType.RECORDING_DOMAINS} />
                    </>
                ) : null}
                <LemonDivider className="my-6" />
                <GroupAnalytics />
                <RestrictedArea Component={AccessControl} minimumAccessLevel={OrganizationMembershipLevel.Admin} />
                <LemonDivider className="my-6" />
                {currentTeam?.access_control && hasAvailableFeature(AvailableFeature.PROJECT_BASED_PERMISSIONING) && (
                    <BindLogic logic={teamMembersLogic} props={{ team: currentTeam }}>
                        {user && <TeamMembers user={user} team={currentTeam} />}
                        <LemonDivider className="my-6" />
                    </BindLogic>
                )}
                <RestrictedArea
                    Component={DangerZone}
                    minimumAccessLevel={OrganizationMembershipLevel.Admin}
                    scope={RestrictionScope.Project}
                />
            </div>
        </div>
    )
}
