import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { urls } from 'scenes/urls'

export function CalendarSyncConfig(): JSX.Element {
    const { integrations, integrationsLoading } = useValues(integrationsLogic)

    const calendarIntegrations = integrations?.filter((integration) => integration.kind === 'google-calendar') ?? []

    return (
        <div className="flex flex-col gap-4">
            {calendarIntegrations.map((integration) => (
                <IntegrationView key={integration.id} integration={integration} />
            ))}
            <div>
                <LemonButton
                    type="secondary"
                    disableClientSideRouting
                    loading={integrationsLoading}
                    to={api.integrations.authorizeUrl({
                        kind: 'google-calendar',
                        next: urls.settings('environment-customer-analytics'),
                    })}
                >
                    {calendarIntegrations.length ? 'Connect another calendar' : 'Connect Google Calendar'}
                </LemonButton>
            </div>
        </div>
    )
}
