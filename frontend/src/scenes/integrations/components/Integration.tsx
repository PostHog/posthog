import { useValues } from 'kea'
import { PropsWithChildren, useMemo } from 'react'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'

import { IntegrationKind, IntegrationType } from '~/types'

export function Integration({ kind, children }: PropsWithChildren<{ kind: IntegrationKind }>): JSX.Element {
    const integrations = useIntegrations(kind)

    return (
        <div className="flex flex-col">
            <div className="flex flex-col gap-y-2">
                {integrations.map((integration) => (
                    <IntegrationView key={integration.id} integration={integration} />
                ))}
                <div className="flex">{children}</div>
            </div>
        </div>
    )
}

export function useIntegrations(kind: IntegrationKind): IntegrationType[] {
    const { getIntegrationsByKind } = useValues(integrationsLogic)

    return useMemo(() => getIntegrationsByKind([kind] satisfies IntegrationKind[]), [getIntegrationsByKind, kind])
}
