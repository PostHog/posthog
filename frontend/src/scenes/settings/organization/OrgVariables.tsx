import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'
import { Button, Skeleton, Text } from '@posthog/quill'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link, LinkPrimitive } from 'lib/lemon-ui/Link'
import { organizationLogic } from 'scenes/organizationLogic'

export function OrganizationVariables(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2 max-w-160">
                {currentOrganization ? (
                    <CodeSnippet compact thing="organization ID">
                        {String(currentOrganization.id)}
                    </CodeSnippet>
                ) : (
                    <Skeleton className="h-9" />
                )}
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Use this ID to identify your organization in the{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to="https://posthog.com/docs/api" />}
                    >
                        PostHog API
                    </Button>
                    .
                </Text>
            </div>
        )
    }

    return (
        <div className="border rounded p-4 space-y-3 bg-bg-light max-w-160">
            {currentOrganization ? (
                <CodeSnippet compact thing="organization ID">
                    {String(currentOrganization.id)}
                </CodeSnippet>
            ) : (
                <LemonSkeleton className="h-9" />
            )}
            <p className="text-muted text-xs mb-0">
                Use this ID to identify your organization in the{' '}
                <Link to="https://posthog.com/docs/api">PostHog API</Link>.
            </p>
        </div>
    )
}
