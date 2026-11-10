import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import type { WorkloadJobSettingsApi, WorkloadProviderApi } from '~/generated/core/api.schemas'

export function WorkloadSetupSnippet({
    provider,
    jobSettings,
}: {
    provider: WorkloadProviderApi
    jobSettings: WorkloadJobSettingsApi
}): JSX.Element {
    const copied = (part: string) => (): void => {
        posthog.capture('workload trust policy snippet copied', { provider: provider.name, part })
    }
    const posthogJson = JSON.stringify(
        {
            ...(jobSettings.host_in_posthog_json ? { host: jobSettings.host } : {}),
            projectId: jobSettings.project_id,
        },
        null,
        4
    )
    return (
        <div className="deprecated-space-y-2">
            <p className="mb-0">
                Set up the job in two steps. Each run then gets a short-lived token for this project, with no key stored
                in {provider.name}.
            </p>
            <p className="mb-0 font-semibold">1. Add this to posthog.json in the repository</p>
            <CodeSnippet language={Language.JSON} thing="posthog.json settings" onCopy={copied('posthog_json')}>
                {posthogJson}
            </CodeSnippet>
            <p className="mb-0 font-semibold">2. Add this to the {provider.name} job that runs hog</p>
            <CodeSnippet language={Language.YAML} thing="snippet" onCopy={copied('job')}>
                {provider.setup_snippet}
            </CodeSnippet>
            <p className="mb-0 text-secondary">
                {jobSettings.host_in_posthog_json
                    ? `Or, instead of posthog.json, set HOG_HOST=${jobSettings.host} and HOG_PROJECT_ID=${jobSettings.project_id} in the job.`
                    : `This PostHog isn't PostHog Cloud, so the job also needs HOG_HOST=${jobSettings.host}.`}
            </p>
            <Link to={provider.docs_url} target="_blank">
                Read the {provider.name} setup guide
            </Link>
        </div>
    )
}
