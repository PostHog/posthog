import { Heading } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import {
    GithubIntegration,
    GitLabIntegration,
    JiraIntegration,
    LinearIntegration,
} from 'scenes/integrations/components/Integrations'
import { urls } from 'scenes/urls'

const NEXT_URL = urls.replaySettings('replay-integrations')

export function ReplayIntegrations(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-6">
                <div className="flex flex-col gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Linear
                    </Heading>
                    <LinearIntegration next={NEXT_URL} />
                </div>
                <div className="flex flex-col gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        GitHub
                    </Heading>
                    <GithubIntegration next={NEXT_URL} connectSurface="settings" />
                </div>
                <div className="flex flex-col gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        GitLab
                    </Heading>
                    <GitLabIntegration />
                </div>
                <div className="flex flex-col gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Jira
                    </Heading>
                    <JiraIntegration next={NEXT_URL} />
                </div>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-y-6">
            <div>
                <h3>Linear</h3>
                <LinearIntegration next={NEXT_URL} />
            </div>
            <div>
                <h3>GitHub</h3>
                <GithubIntegration next={NEXT_URL} connectSurface="settings" />
            </div>
            <div>
                <h3>GitLab</h3>
                <GitLabIntegration />
            </div>
            <div>
                <h3>Jira</h3>
                <JiraIntegration next={NEXT_URL} />
            </div>
        </div>
    )
}
