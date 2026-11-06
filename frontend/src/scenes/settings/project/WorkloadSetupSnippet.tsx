import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import type { WorkloadJobSettingsApi } from '~/generated/core/api.schemas'

export function WorkloadSetupSnippet({
    snippet,
    providerName,
    docsUrl,
    jobSettings,
}: {
    snippet: string
    providerName: string
    docsUrl: string
    jobSettings: WorkloadJobSettingsApi
}): JSX.Element {
    const copied = (part: string) => (): void => {
        posthog.capture('workload trust policy snippet copied', { provider: providerName, part })
    }
    return (
        <div className="deprecated-space-y-2">
            <p className="mb-0">
                The job then gets a short-lived token for this project on each run, with no key stored in {providerName}
                .
            </p>
            <p className="mb-0 font-semibold">1. Add this to posthog.json in the repository</p>
            <CodeSnippet language={Language.JSON} thing="posthog.json settings" onCopy={copied('posthog_json')}>
                {jobSettings.posthog_json}
            </CodeSnippet>
            <p className="mb-0 font-semibold">2. Add this to the {providerName} job that runs hog</p>
            <CodeSnippet language={Language.YAML} thing="snippet" onCopy={copied('job')}>
                {snippet}
            </CodeSnippet>
            <p className="mb-0 text-secondary">
                {jobSettings.host_in_posthog_json
                    ? `Or, instead of posthog.json, set HOG_HOST=${jobSettings.host} and HOG_PROJECT_ID=${jobSettings.project_id} in the job.`
                    : `This PostHog isn't PostHog Cloud, so the job also needs HOG_HOST=${jobSettings.host}.`}
            </p>
            <Link to={docsUrl} target="_blank">
                Read the {providerName} setup guide
            </Link>
        </div>
    )
}
