import {
    GithubIntegration,
    GitLabIntegration,
    JiraIntegration,
    LinearIntegration,
} from 'scenes/integrations/components/Integrations'
import { urls } from 'scenes/urls'

const NEXT_URL = urls.replaySettings('replay-integrations')

export function ReplayIntegrations(): JSX.Element {
    return (
        <div className="flex flex-col gap-y-6">
            <div>
                <h3>Linear</h3>
                <LinearIntegration next={NEXT_URL} />
            </div>
            <div>
                <h3>GitHub</h3>
                <GithubIntegration next={NEXT_URL} />
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
