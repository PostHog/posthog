import { IconExternal, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

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
                integrationsOfKind?.length
                    ? {
                          items: [
                              ...(integrationsOfKind?.map((integration) => ({
                                  icon: <img src={integration.icon_url} className="w-6 h-6 rounded" />,
                                  onClick: () => onChange?.(integration.id),
                                  active: integration.id === value,
                                  label: integration.name,
                              })) || []),
                          ],
                      }
                    : null,
                {
                    items: [
                        {
                            to: api.integrations.authorizeUrl({
                                kind,
                                next: `${window.location.pathname}?integration_target=${schema.key}`,
                            }),
                            disableClientSideRouting: true,
                            label: integrationsOfKind?.length
                                ? `Connect to a different ${kind} integration`
                                : `Connect to ${kind}`,
                        },
                    ],
                },
                {
                    items: [
                        {
                            to: urls.settings('project-integrations'),
                            label: 'Manage integrations',
                            sideIcon: <IconExternal />,
                        },
                        value
                            ? {
                                  onClick: () => onChange?.(null),
                                  label: 'Clear',
                                  sideIcon: <IconX />,
                              }
                            : null,
                    ],
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
