import { BindLogic, useValues } from 'kea'
import { IPCapture } from './IPCapture'
import { SessionRecording } from './SessionRecording'
import { WebhookIntegration } from './WebhookIntegration'
import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { teamLogic } from 'scenes/teamLogic'
import { DangerZone } from './ProjectDangerZone'
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
import { LemonDivider, LemonLabel } from '@posthog/lemon-ui'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IngestionInfo } from './IngestionInfo'
import { ExtraTeamSettings } from './ExtraTeamSettings'
import { WeekStartConfig } from './WeekStartConfig'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SurveySettings } from './Survey'
import { ProjectDisplayName } from './ProjectSettings'

export const scene: SceneExport = {
    component: ProjectSettings,
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
                <GroupAnalytics />
                <SurveySettings />
                <ExtraTeamSettings />
            </div>
        </div>
    )
}
