import { useValues } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { Link } from 'lib/lemon-ui/Link'
import { organizationLogic } from 'scenes/organizationLogic'

export function OrganizationVariables(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)

    return (
        <div className="border rounded p-4 space-y-3 bg-bg-light max-w-160">
            <LemonLabel className="mb-0">Organization ID</LemonLabel>
            <CodeSnippet compact thing="organization ID">
                {String(currentOrganization?.id || '')}
            </CodeSnippet>
            <p className="text-muted text-xs mb-0">
                Use this ID to identify your organization in the{' '}
                <Link to="https://posthog.com/docs/api">PostHog API</Link>.
            </p>
        </div>
    )
}
