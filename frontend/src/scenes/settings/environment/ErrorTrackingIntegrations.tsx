import { PostHogFeature } from 'posthog-js/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { GitLabIntegration, GithubIntegration, JiraIntegration, LinearIntegration } from './Integrations'

export function ErrorTrackingIntegrations(): JSX.Element {
    return (
        <div className="flex flex-col gap-y-6">
            <div>
                <h3>Linear</h3>
                <LinearIntegration />
            </div>
            <div>
                <h3>GitHub</h3>
                <GithubIntegration />
            </div>
            <div>
                <h3>GitLab</h3>
                <GitLabIntegration />
            </div>
            <PostHogFeature flag={FEATURE_FLAGS.ERROR_TRACKING_JIRA_INTEGRATION} match={true}>
                <div>
                    <h3>Jira</h3>
                    <JiraIntegration />
                </div>
            </PostHogFeature>
        </div>
    )
}
