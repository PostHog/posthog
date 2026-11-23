import { Heading } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import {
    GitLabIntegration,
    GithubIntegration,
    JiraIntegration,
    LinearIntegration,
} from 'scenes/integrations/components/Integrations'
import { urls } from 'scenes/urls'

import IconGitHub from 'public/services/github.png'
import IconGitLab from 'public/services/gitlab.png'
import IconJira from 'public/services/jira.svg'
import IconLinear from 'public/services/linear.png'

const NEXT_URL = urls.settings('environment-error-tracking', 'error-tracking-integrations')

function IntegrationHeading({ icon, label }: { icon: string; label: string }): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <Heading size="sm" render={<h3 className="m-0 flex items-center gap-2" />}>
                <img src={icon} alt="" className="w-5 h-5" />
                {label}
            </Heading>
        )
    }

    return (
        <h3 className="flex items-center gap-2">
            <img src={icon} alt="" className="w-5 h-5" />
            {label}
        </h3>
    )
}

export function ErrorTrackingIntegrations(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const sectionClassName = todayRailNav ? 'flex flex-col gap-2' : undefined

    return (
        <div className="flex flex-col gap-y-6">
            <div className={sectionClassName}>
                <IntegrationHeading icon={IconLinear} label="Linear" />
                <LinearIntegration next={NEXT_URL} />
            </div>
            <div className={sectionClassName}>
                <IntegrationHeading icon={IconGitHub} label="GitHub" />
                <GithubIntegration next={NEXT_URL} connectSurface="settings" />
            </div>
            <div className={sectionClassName}>
                <IntegrationHeading icon={IconGitLab} label="GitLab" />
                <GitLabIntegration />
            </div>
            <div className={sectionClassName}>
                <IntegrationHeading icon={IconJira} label="Jira" />
                <JiraIntegration next={NEXT_URL} />
            </div>
        </div>
    )
}
