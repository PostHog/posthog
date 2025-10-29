import { useActions, useValues } from 'kea'

import { IconExternal, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSkeleton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { getIntegrationNameFromKind } from 'lib/integrations/utils'
import { DatabricksSetupModal } from 'scenes/integrations/databricks/DatabricksSetupModal'
import { GitLabSetupModal } from 'scenes/integrations/gitlab/GitLabSetupModal'
import { urls } from 'scenes/urls'

import { CyclotronJobInputSchemaType } from '~/types'

import { ChannelSetupModal } from 'products/workflows/frontend/Channels/ChannelSetupModal'

export type IntegrationConfigureProps = {
    value?: number
    onChange?: (value: number | null) => void
    redirectUrl?: string
    schema?: CyclotronJobInputSchemaType
    integration?: string
    beforeRedirect?: () => void
}

export function IntegrationChoice({
    onChange,
    value,
    schema,
    integration,
    redirectUrl,
    beforeRedirect,
}: IntegrationConfigureProps): JSX.Element | null {
    const { integrationsLoading, integrations, newIntegrationModalKind } = useValues(integrationsLogic)
    const { newGoogleCloudKey, openNewIntegrationModal, closeNewIntegrationModal } = useActions(integrationsLogic)
    const kind = integration

    const integrationsOfKind = integrations?.filter((x) => x.kind === kind)
    const integrationKind = integrationsOfKind?.find((integration) => integration.id === value)

    if (!kind) {
        return null
    }

    if (integrationsLoading) {
        return <LemonSkeleton className="h-10" />
    }

    const kindName = getIntegrationNameFromKind(kind)

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

    const handleNewDatabricksIntegration = (integrationId: number | undefined): void => {
        if (integrationId) {
            onChange?.(integrationId)
        }
        closeNewIntegrationModal()
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
                ['google-pubsub', 'google-cloud-storage'].includes(kind)
                    ? {
                          items: [
                              {
                                  onClick: () => uploadKey(kind),
                                  label: 'Upload Google Cloud .json key file',
                              },
                          ],
                      }
                    : ['email'].includes(kind)
                      ? {
                            items: [
                                {
                                    to: urls.workflows('channels'),
                                    label: 'Configure new email sender domain',
                                },
                            ],
                        }
                      : ['twilio'].includes(kind)
                        ? {
                              items: [
                                  {
                                      label: 'Configure new Twilio account',
                                      onClick: () => openNewIntegrationModal('twilio'),
                                  },
                              ],
                          }
                        : ['databricks'].includes(kind)
                          ? {
                                items: [
                                    {
                                        label: 'Configure new Databricks account',
                                        onClick: () => openNewIntegrationModal('databricks'),
                                    },
                                ],
                            }
                          : ['gitlab'].includes(kind)
                            ? {
                                  items: [
                                      {
                                          label: 'Configure new GitLab account',
                                          onClick: () => openNewIntegrationModal('gitlab'),
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
                                          onClick: beforeRedirect,
                                          label: integrationsOfKind?.length
                                              ? `Connect to a different integration for ${kindName}`
                                              : `Connect to ${kindName}`,
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

    return (
        <>
            {integrationKind ? (
                <IntegrationView schema={schema} integration={integrationKind} suffix={button} />
            ) : (
                button
            )}

            <ChannelSetupModal
                isOpen={newIntegrationModalKind === 'twilio'}
                channelType="twilio"
                integration={integrationKind || undefined}
                onComplete={closeNewIntegrationModal}
            />
            <DatabricksSetupModal
                isOpen={newIntegrationModalKind === 'databricks'}
                integration={integrationKind || undefined}
                onComplete={handleNewDatabricksIntegration}
            />
            <GitLabSetupModal isOpen={newIntegrationModalKind === 'gitlab'} onComplete={closeNewIntegrationModal} />
        </>
    )
}
