import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

export function WorkloadSetupSnippet({
    snippet,
    providerName,
    docsUrl,
}: {
    snippet: string
    providerName: string
    docsUrl: string
}): JSX.Element {
    return (
        <div className="deprecated-space-y-2">
            <p className="mb-0">
                Add this to the {providerName} job that runs hog. The job then gets a short-lived token for this project
                on each run, with no key stored in {providerName}.
            </p>
            <CodeSnippet
                language={Language.YAML}
                thing="snippet"
                onCopy={() => posthog.capture('workload trust policy snippet copied', { provider: providerName })}
            >
                {snippet}
            </CodeSnippet>
            <Link to={docsUrl} target="_blank">
                Read the {providerName} setup guide
            </Link>
        </div>
    )
}
