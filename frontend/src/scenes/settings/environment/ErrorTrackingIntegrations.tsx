import IconGitHub from 'public/services/github.png'
import IconGitLab from 'public/services/gitlab.png'
import IconJira from 'public/services/jira.svg'
import IconLinear from 'public/services/linear.png'

import { GitLabIntegration, GithubIntegration, JiraIntegration, LinearIntegration } from './Integrations'

export function ErrorTrackingIntegrations(): JSX.Element {
    return (
        <div className="flex flex-col gap-y-6">
            <div>
                <h3 className="flex items-center gap-2">
                    <img src={IconLinear} alt="" className="w-5 h-5" />
                    Linear
                </h3>
                <LinearIntegration />
            </div>
            <div>
                <h3 className="flex items-center gap-2">
                    <img src={IconGitHub} alt="" className="w-5 h-5" />
                    GitHub
                </h3>
                <GithubIntegration />
            </div>
            <div>
                <h3 className="flex items-center gap-2">
                    <img src={IconGitLab} alt="" className="w-5 h-5" />
                    GitLab
                </h3>
                <GitLabIntegration />
            </div>
            <div>
                <h3 className="flex items-center gap-2">
                    <img src={IconJira} alt="" className="w-5 h-5" />
                    Jira
                </h3>
                <JiraIntegration />
            </div>
        </div>
    )
}
