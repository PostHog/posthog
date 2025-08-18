import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { IntegrationView } from 'lib/integrations/IntegrationView'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { IntegrationKind } from '~/types'

export function IntegrationsList({
    titleText = 'All connected integrations are listed here. These integrations may be used for various purposes, such as data warehouse or pipeline destinations. To connect a new integration, visit the relevant product area.',
    onlyKinds,
    omitKinds,
}: {
    onlyKinds?: IntegrationKind[]
    omitKinds?: IntegrationKind[]
    titleText?: string
}): JSX.Element {
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const filteredIntegrations = integrations?.filter((integration) => {
        if (onlyKinds && !onlyKinds.includes(integration.kind)) {
            return false
        }
        if (omitKinds && omitKinds.includes(integration.kind)) {
            return false
        }
        return true
    })

    return (
        <div>
            {titleText ? <p>{titleText}</p> : null}

            <div className="deprecated-space-y-2">
                {filteredIntegrations?.length
                    ? filteredIntegrations.map((integration) => (
                          <IntegrationView key={integration.id} integration={integration} />
                      ))
                    : integrationsLoading && <LemonSkeleton className="h-10" />}
            </div>
        </div>
    )
}
