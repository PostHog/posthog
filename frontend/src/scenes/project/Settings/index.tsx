import { useState } from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import { IPCapture } from './IPCapture'
import { SessionRecording } from './SessionRecording'
import { WebhookIntegration } from './WebhookIntegration'
import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { ToolbarSettings } from './ToolbarSettings'
import { teamLogic } from 'scenes/teamLogic'
import { DangerZone } from './DangerZone'
import { PageHeader } from 'lib/components/PageHeader'
import { Link } from 'lib/lemon-ui/Link'
import { RestrictedArea, RestrictionScope } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { TestAccountFiltersConfig } from './TestAccountFiltersConfig'
import { TimezoneConfig } from './TimezoneConfig'
import { DataAttributes } from 'scenes/project/Settings/DataAttributes'
import { AvailableFeature, InsightType, TeamType } from '~/types'
import { TeamMembers } from './TeamMembers'
import { teamMembersLogic } from './teamMembersLogic'
import { AccessControl } from './AccessControl'
import { PathCleaningFiltersConfig } from './PathCleaningFiltersConfig'
import { userLogic } from 'scenes/userLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { CorrelationConfig } from './CorrelationConfig'
import { urls } from 'scenes/urls'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { GroupAnalytics } from 'scenes/project/Settings/GroupAnalytics'
import { PersonDisplayNameProperties } from './PersonDisplayNameProperties'
import { SlackIntegration } from './SlackIntegration'
import { LemonButton, LemonDivider, LemonInput, LemonLabel } from '@posthog/lemon-ui'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IngestionInfo } from './IngestionInfo'
import { ExtraTeamSettings } from './ExtraTeamSettings'
import { WeekStartConfig } from './WeekStartConfig'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SurveySettings } from './Survey'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

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
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { location } = useValues(router)
    const { user, hasAvailableFeature } = useValues(userLogic)
    const hasAdvancedPaths = user?.organization?.available_features?.includes(AvailableFeature.PATHS_ADVANCED)
    const { featureFlags } = useValues(featureFlagLogic)

    useAnchor(location.hash)

    const LoadingComponent = (): JSX.Element => (
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
                {currentTeamLoading && !currentTeam ? <LoadingComponent /> : <DisplayName />}
                <LemonDivider className="my-6" />
                {currentTeamLoading && !currentTeam ? (
                    <LoadingComponent />
                ) : (
                    <IngestionInfo loadingComponent={<LoadingComponent />} />
                )}
                <LemonDivider className="my-6" />
                <h2 className="subtitle" id="date-and-time">
                    Date and time
                </h2>
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
                <LemonDivider className="my-6" />
                <h2 className="subtitle" id="internal-users-filtering">
                    Filter out internal and test users
                </h2>
                <p>
                    Increase the quality of your analytics results by filtering out events from internal sources, such
                    as team members, test accounts, or development environments.{' '}
                    <strong>
                        The filters you apply here are added as extra filters when the toggle is switched on.
                    </strong>{' '}
                    So, if you apply a cohort, it means you will only match users in that cohort.
                </p>
                <LemonBanner type="info">
                    Events and recordings will still be ingested and saved, but they will be excluded from any queries
                    where the "Filter out internal and test users" toggle is set. You can learn how to{' '}
                    <Link to="https://posthog.com/tutorials/fewer-unwanted-events" target="_blank">
                        capture fewer events
                    </Link>{' '}
                    or how to{' '}
                    <Link to="https://posthog.com/tutorials/limit-session-recordings" target="_blank">
                        capture fewer recordings
                    </Link>{' '}
                    in our docs.
                </LemonBanner>
                <div className={'mt-4'}>
                    <strong>Example filters</strong>
                    <ul className="list-disc pl-4 mb-2">
                        <li>
                            "<strong>Email</strong> does not contain <strong>yourcompany.com</strong>" to exclude all
                            events from your company's team members.
                        </li>
                        <li>
                            "<strong>Host</strong> does not contain <strong>localhost</strong>" to exclude all events
                            from local development environments.
                        </li>
                    </ul>
                </div>
                <TestAccountFiltersConfig />
                <LemonDivider className="my-6" />
                <CorrelationConfig />
                {hasAdvancedPaths && (
                    <>
                        <LemonDivider className="my-6" />
                        <h2 className="subtitle" id="path_cleaning_filtering">
                            Path cleaning rules
                            <LemonTag type="warning" className="uppercase" style={{ marginLeft: 8 }}>
                                Beta
                            </LemonTag>
                        </h2>
                        <p>
                            Make your <Link to={urls.insightNew({ insight: InsightType.PATHS })}>Paths</Link> clearer by
                            aliasing one or multiple URLs.{' '}
                            <i>
                                Example: <code>http://tenant-one.mydomain.com/accounts</code> and{' '}
                                <code>http://tenant-two.mydomain.com/accounts</code> can become a single{' '}
                                <code>/accounts</code> path.
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
                <div id="authorized-urls" />
                <h2 className="subtitle" id="urls">
                    Authorized URLs
                </h2>
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
                <LemonDivider className="my-6" />
                <h2 className="subtitle" id="attributes">
                    Data attributes
                </h2>
                <DataAttributes />
                <LemonDivider className="my-6" />
                <h2 className="subtitle" id="person-display-name">
                    Person display name
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
                <SessionRecording />
                <LemonDivider className="my-6" />
                <GroupAnalytics />
                {featureFlags[FEATURE_FLAGS.SURVEYS_SITE_APP_DEPRECATION] && <SurveySettings />}
                <ExtraTeamSettings />
                <RestrictedArea Component={AccessControl} minimumAccessLevel={OrganizationMembershipLevel.Admin} />
                <LemonDivider className="my-6" />
                {currentTeam?.access_control && hasAvailableFeature(AvailableFeature.PROJECT_BASED_PERMISSIONING) && (
                    <BindLogic logic={teamMembersLogic} props={{ team: currentTeam }}>
                        {user && <TeamMembers user={user} team={currentTeam as TeamType} />}
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
