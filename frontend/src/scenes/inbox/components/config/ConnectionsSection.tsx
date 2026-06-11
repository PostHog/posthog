import { useValues } from 'kea'

import { IconCheckCircle, IconGithub } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { urls } from 'scenes/urls'

export function ConnectionsSection(): JSX.Element {
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)

    const githubIntegrations = getIntegrationsByKind(['github'])
    const hasGithubIntegration = githubIntegrations.length > 0

    return (
        <div className="flex items-center justify-between gap-4 rounded border bg-bg-light px-3 py-2.5">
            <div className="flex items-start gap-3 min-w-0">
                <IconGithub className="size-5 shrink-0 mt-0.5" />
                <div className="min-w-0">
                    <div className="font-medium text-sm flex items-center gap-1.5">
                        GitHub
                        {hasGithubIntegration && !integrationsLoading && (
                            <span className="inline-flex items-center gap-1 text-xs text-success font-normal">
                                <IconCheckCircle className="size-3.5" />
                                Connected
                            </span>
                        )}
                    </div>
                    <p className="text-xs text-secondary mt-0.5 mb-0 max-w-xl">
                        Foundational integration agents read from and write pull requests to.
                    </p>
                </div>
            </div>
            <LemonButton
                type="secondary"
                size="small"
                to={urls.settings('environment-integrations', 'integration-github')}
                targetBlank
            >
                {hasGithubIntegration ? 'Manage' : 'Connect'}
            </LemonButton>
        </div>
    )
}
