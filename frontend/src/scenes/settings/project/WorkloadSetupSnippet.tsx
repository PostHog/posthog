import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { WorkloadJobSettingsApi, WorkloadProviderApi } from '~/generated/core/api.schemas'

export function WorkloadSetupSnippet({
    provider,
    jobSettings,
}: {
    provider: WorkloadProviderApi
    jobSettings: WorkloadJobSettingsApi
}): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

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
    const posthogJsonSnippet = (
        <CodeSnippet language={Language.JSON} thing="posthog.json settings" onCopy={copied('posthog_json')}>
            {posthogJson}
        </CodeSnippet>
    )
    const jobSnippet = (
        <CodeSnippet language={Language.YAML} thing="snippet" onCopy={copied('job')}>
            {provider.setup_snippet}
        </CodeSnippet>
    )
    const hostNote = jobSettings.host_in_posthog_json
        ? `Or, instead of posthog.json, set HOG_HOST=${jobSettings.host} and HOG_PROJECT_ID=${jobSettings.project_id} in the job.`
        : `This PostHog isn't PostHog Cloud, so the job also needs HOG_HOST=${jobSettings.host}.`

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    Set up the job in two steps. Each run then gets a short-lived token for this project, with no key
                    stored in {provider.name}.
                </Text>
                <Text size="xs" weight="semibold" render={<p className="m-0" />}>
                    1. Add this to posthog.json in the repository
                </Text>
                {posthogJsonSnippet}
                <Text size="xs" weight="semibold" render={<p className="m-0" />}>
                    2. Add this to the {provider.name} job that runs hog
                </Text>
                {jobSnippet}
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {hostNote}
                </Text>
                <div>
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={provider.docs_url} target="_blank" />}
                    >
                        Read the {provider.name} setup guide
                    </Button>
                </div>
            </div>
        )
    }

    return (
        <div className="deprecated-space-y-2">
            <p className="mb-0">
                Set up the job in two steps. Each run then gets a short-lived token for this project, with no key stored
                in {provider.name}.
            </p>
            <p className="mb-0 font-semibold">1. Add this to posthog.json in the repository</p>
            {posthogJsonSnippet}
            <p className="mb-0 font-semibold">2. Add this to the {provider.name} job that runs hog</p>
            {jobSnippet}
            <p className="mb-0 text-secondary">{hostNote}</p>
            <Link to={provider.docs_url} target="_blank">
                Read the {provider.name} setup guide
            </Link>
        </div>
    )
}
