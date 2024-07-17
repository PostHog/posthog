import { LemonButton, LemonMenu, LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { capitalizeFirstLetter } from 'lib/utils'

import { HogFunctionInputSchemaType } from '~/types'

type HogFunctionInputIntegrationConfigureProps = {
    value?: number
    onChange?: (value: number | null) => void
}

export type HogFunctionInputIntegrationProps = HogFunctionInputIntegrationConfigureProps & {
    schema: HogFunctionInputSchemaType
}

export function HogFunctionInputIntegration({ schema, ...props }: HogFunctionInputIntegrationProps): JSX.Element {
    return <HogFunctionIntegrationChoice {...props} schema={schema} />
    return (
        <div className="text-danger">
            <p>Unsupported integration type: {schema.integration}</p>
        </div>
    )
}

function HogFunctionIntegrationChoice({
    onChange,
    value,
    schema,
}: HogFunctionInputIntegrationProps): JSX.Element | null {
    const { integrationsLoading, integrations } = useValues(integrationsLogic)
    const kind = schema.integration
    const integrationsOfKind = integrations?.filter((x) => x.kind === kind)
    const integration = integrationsOfKind?.find((integration) => integration.id === value)

    if (!kind) {
        return null
    }

    if (integrationsLoading) {
        return <LemonSkeleton className="h-10" />
    }

    const button = (
        <LemonMenu
            items={[
                ...(integrationsOfKind?.map((integration) => ({
                    icon: <img src={integration.icon_url} className="w-6 h-6" />,
                    onClick: () => onChange?.(integration.id),
                    label: integration.name,
                })) || []),
                {
                    to: api.integrations.authorizeUrl({
                        kind,
                        next: window.location.pathname,
                    }),
                    label: 'Add to different Slack workspace',
                },
            ]}
        >
            {integration ? (
                <LemonButton type="secondary">Change</LemonButton>
            ) : (
                <LemonButton type="secondary">Choose {capitalizeFirstLetter(kind)} connection</LemonButton>
            )}
        </LemonMenu>
    )

    return <>{integration ? <IntegrationView integration={integration} suffix={button} /> : button}</>
}
