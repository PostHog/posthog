import { LemonBanner } from '@posthog/lemon-ui'
import api from 'lib/api'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { IntegrationScopesWarning } from 'lib/integrations/IntegrationScopesWarning'

import { CyclotronJobInputSchemaType, IntegrationType } from '~/types'

export function IntegrationView({
    integration,
    suffix,
    schema,
}: {
    integration: IntegrationType
    suffix?: JSX.Element
    schema?: CyclotronJobInputSchemaType
}): JSX.Element {
    const errors = (integration.errors && integration.errors?.split(',')) || []

    return (
        <div className="rounded border bg-surface-primary">
            <div className="flex justify-between items-center p-2">
                <div className="flex gap-4 items-center ml-2">
                    <img src={integration.icon_url} className="w-10 h-10 rounded" />
                    <div>
                        <div>
                            Connected to <strong>{integration.display_name}</strong>
                        </div>
                        {integration.created_by ? (
                            <UserActivityIndicator
                                at={integration.created_at}
                                by={integration.created_by}
                                prefix="Updated"
                                className="text-secondary"
                            />
                        ) : null}
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
