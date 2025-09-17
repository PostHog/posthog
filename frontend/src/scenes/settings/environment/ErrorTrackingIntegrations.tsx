import { GithubIntegration, LinearIntegration } from './Integrations'

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
        </div>
    )
}
