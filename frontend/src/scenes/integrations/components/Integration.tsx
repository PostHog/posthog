import { useValues } from 'kea'
import { PropsWithChildren, useMemo } from 'react'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { cn } from 'lib/utils/css-classes'

import { IntegrationKind, IntegrationType } from '~/types'

export function Integration({
    kind,
    centered,
    children,
}: PropsWithChildren<{ kind: IntegrationKind; centered?: boolean }>): JSX.Element {
    const integrations = useIntegrations(kind)

    return (
        <div className="flex flex-col">
            <div className="flex flex-col gap-y-2">
                {integrations.map((integration) => (
                    <IntegrationView key={integration.id} integration={integration} />
                ))}
                <div className={cn('flex', centered && 'justify-center')}>{children}</div>
            </div>
        </div>
    )
}

export function useIntegrations(kind: IntegrationKind): IntegrationType[] {
    const { getIntegrationsByKind } = useValues(integrationsLogic)

    return useMemo(() => getIntegrationsByKind([kind] satisfies IntegrationKind[]), [getIntegrationsByKind, kind])
}
