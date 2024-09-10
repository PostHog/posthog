import { IconExternal, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

export type IntegrationConfigureProps = {
    value?: number
    onChange?: (value: number | null) => void
    redirectUrl?: string
    integration?: string
}

export function IntegrationChoice({
    onChange,
    value,
    integration,
    redirectUrl,
}: IntegrationConfigureProps): JSX.Element | null {
    const { integrationsLoading, integrations } = useValues(integrationsLogic)
    const { newGoogleCloudKey } = useActions(integrationsLogic)
    const kind = integration
    const integrationsOfKind = integrations?.filter((x) => x.kind === kind)
    const integrationKind = integrationsOfKind?.find((integration) => integration.id === value)

    if (!kind) {
        return null
    }

    if (integrationsLoading) {
        return <LemonSkeleton className="h-10" />
    }

    const kindName = kind == 'google-pubsub' ? 'Google Cloud Pub/Sub' : capitalizeFirstLetter(kind)

    function uploadKey(kind: string): void {
        const input = document.createElement('input')
        input.type = 'file'
        input.accept = '.json'
        input.onchange = async (e) => {
            const file = (e.target as HTMLInputElement).files?.[0]
            if (!file) {
                return
            }
            newGoogleCloudKey(kind, file, (integration) => onChange?.(integration.id))
        }
        input.click()
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
                                  label: integration.display_name,
                              })) || []),
                          ],
                      }
                    : null,
                kind.startsWith('google-')
                    ? {
                          items: [
                              {
                                  onClick: () => uploadKey(kind),
                                  label: 'Upload Google Cloud .json key file',
                              },
                          ],
                      }
                    : {
                          items: [
                              {
                                  to: api.integrations.authorizeUrl({
                                      kind,
                                      next: redirectUrl,
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
            {integrationKind ? (
                <LemonButton type="secondary">Change</LemonButton>
            ) : (
                <LemonButton type="secondary">Choose {kindName} connection</LemonButton>
            )}
        </LemonMenu>
    )

    return <>{integrationKind ? <IntegrationView integration={integrationKind} suffix={button} /> : button}</>
}
