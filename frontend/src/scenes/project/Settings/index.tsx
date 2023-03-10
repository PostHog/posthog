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
import { AvailableFeature, InsightType } from '~/types'
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
import { IconInfo } from 'lib/lemon-ui/icons'
import { PersonDisplayNameProperties } from './PersonDisplayNameProperties'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { SlackIntegration } from './SlackIntegration'
import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IngestionInfo } from './IngestionInfo'

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
                <SessionRecording />
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
