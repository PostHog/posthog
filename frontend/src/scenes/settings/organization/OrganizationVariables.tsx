import { useValues } from 'kea'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { Link } from 'lib/lemon-ui/Link'
import { organizationLogic } from 'scenes/organizationLogic'

export function OrganizationVariables(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)

    return (
        <div className="flex items-start gap-4 flex-wrap">
            <div className="flex-1">
                <h3 id="organization-id" className="min-w-[25rem]">
                    Organization ID
                </h3>
                <p>
                    You can use this ID to reference your organization in our{' '}
                    <Link to="https://posthog.com/docs/api">API</Link>.
                </p>
                <CodeSnippet thing="organization ID">{String(currentOrganization?.id || '')}</CodeSnippet>
            </div>
        </div>
    )
}
