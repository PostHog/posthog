import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { IntegrationScopesWarning } from 'lib/integrations/IntegrationScopesWarning'
import { IconBranch, IconOpenInNew } from 'lib/lemon-ui/icons'

import { CyclotronJobInputSchemaType, IntegrationType } from '~/types'

import { integrationsLogic } from './integrationsLogic'

export function IntegrationView({
    integration,
    suffix,
    schema,
}: {
    integration: IntegrationType
    suffix?: JSX.Element
    schema?: CyclotronJobInputSchemaType
}): JSX.Element {
    const { deleteIntegration } = useActions(integrationsLogic)

    const errors = (integration.errors && integration.errors?.split(',')) || []
    const { githubRepositoriesLoading, getGitHubRepositories } = useValues(integrationsLogic)
    const { loadGitHubRepositories } = useActions(integrationsLogic)

    const isGitHub = integration.kind === 'github'
    const repositories = isGitHub ? getGitHubRepositories(integration.id) : []

    useEffect(() => {
        if (isGitHub) {
            loadGitHubRepositories(integration.id)
        }
    }, [isGitHub, integration.id, loadGitHubRepositories])

    suffix = suffix || (
        <div className="flex flex-row gap-2">
            <LemonButton
                type="secondary"
                status="danger"
                onClick={() => deleteIntegration(integration.id)}
                icon={<IconTrash />}
            >
                Disconnect
            </LemonButton>
        </div>
    )

    return (
        <div className="rounded border bg-surface-primary">
            <div className="flex justify-between items-center p-2">
                <div className="flex gap-4 items-center ml-2">
                    <img src={integration.icon_url} className="w-10 h-10 rounded" />
                    <div>
                        <div className="flex gap-2">
                            <span>
                                Connected to <strong>{integration.display_name}</strong>
                            </span>
                        </div>
                        {integration.created_by ? (
                            <UserActivityIndicator
                                at={integration.created_at}
                                by={integration.created_by}
                                prefix="Updated"
                                className="text-secondary"
                            />
                        ) : null}
                        {isGitHub && (
                            <div className="mt-1">
                                {githubRepositoriesLoading ? (
                                    <div className="flex items-center gap-1 text-xs text-muted">
                                        <Spinner className="text-sm" />
                                        Loading repositories...
                                    </div>
                                ) : repositories.length > 0 ? (
                                    <div className="flex items-center gap-2">
                                        <div className="text-xs text-muted">
                                            <IconBranch className="inline mr-1" />
                                            {repositories.length} repositor{repositories.length === 1 ? 'y' : 'ies'}:{' '}
                                            {repositories.join(', ')}
                                        </div>
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            icon={<IconOpenInNew />}
                                            onClick={() => {
                                                const installationId = integration.config?.installation_id
                                                if (installationId) {
                                                    window.open(
                                                        `https://github.com/settings/installations/${installationId}`,
                                                        '_blank'
                                                    )
                                                }
                                            }}
                                            tooltip="Manage repository access on GitHub"
                                        />
                                    </div>
                                ) : (
                                    <div className="flex items-center gap-2">
                                        <div className="text-xs text-muted">
                                            <IconBranch className="inline mr-1" />
                                            No repositories accessible
                                        </div>
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            icon={<IconOpenInNew />}
                                            onClick={() => {
                                                const installationId = integration.config?.installation_id
                                                if (installationId) {
                                                    window.open(
                                                        `https://github.com/settings/installations/${installationId}`,
                                                        '_blank'
                                                    )
                                                }
                                            }}
                                            tooltip="Configure repository access"
                                        />
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                </div>

                {suffix}
            </div>

            {errors.length > 0 ? (
                <div className="p-2">
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Reconnect',
                            disableClientSideRouting: true,
                            to: api.integrations.authorizeUrl({
                                kind: integration.kind,
                                next: window.location.pathname,
                            }),
                        }}
                    >
                        {errors[0] === 'TOKEN_REFRESH_FAILED'
                            ? 'Authentication token could not be refreshed. Please reconnect.'
                            : `There was an error with this integration: ${errors[0]}`}
                    </LemonBanner>
                </div>
            ) : (
                <IntegrationScopesWarning integration={integration} schema={schema} />
            )}
        </div>
    )
}
