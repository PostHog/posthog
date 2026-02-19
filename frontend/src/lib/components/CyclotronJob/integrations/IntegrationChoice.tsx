import { useActions, useValues } from 'kea'

import { IconExternal, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSkeleton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { getIntegrationNameFromKind } from 'lib/integrations/utils'
import { urls } from 'scenes/urls'

import { CyclotronJobInputSchemaType } from '~/types'

import { getAllRegisteredIntegrationSetups, getIntegrationSetup } from './integrationSetupRegistry'
// Side-effect import: register all integration setups
import './integrationSetups'

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

    function uploadKey(kindForUpload: string): void {
        const input = document.createElement('input')
        input.type = 'file'
        input.accept = '.json'
        input.onchange = async (e) => {
            const file = (e.target as HTMLInputElement).files?.[0]
            if (!file) {
                return
            }
            newGoogleCloudKey(kindForUpload, file, (integ) => onChange?.(integ.id))
        }
        input.click()
    }

    const handleModalComplete = (integrationId?: number): void => {
        if (typeof integrationId === 'number') {
            onChange?.(integrationId)
        }
        closeNewIntegrationModal()
    }

    const setupDef = getIntegrationSetup(kind)
    const setupMenuItem = setupDef
        ? setupDef.menuItem({ kind, openModal: openNewIntegrationModal, uploadKey })
        : {
              to: api.integrations.authorizeUrl({ kind, next: redirectUrl }),
              disableClientSideRouting: true,
              onClick: beforeRedirect,
              label: integrationsOfKind?.length
                  ? `Connect to a different integration for ${kindName}`
                  : `Connect to ${kindName}`,
          }

    const button = (
        <LemonMenu
            items={[
                integrationsOfKind?.length
                    ? {
                          items: [
                              ...(integrationsOfKind?.map((integ) => ({
                                  icon: <img src={integ.icon_url} className="w-6 h-6 rounded" />,
                                  onClick: () => onChange?.(integ.id),
                                  active: integ.id === value,
                                  label: integ.display_name,
                              })) || []),
                          ],
                      }
                    : null,
                { items: [setupMenuItem] },
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

            {getAllRegisteredIntegrationSetups()
                .filter((def) => def.SetupModal)
                .map((def) => {
                    const modalKind = Array.isArray(def.kind) ? def.kind[0] : def.kind
                    const SetupModalComponent = def.SetupModal!
                    return (
                        <SetupModalComponent
                            key={modalKind}
                            isOpen={newIntegrationModalKind === modalKind}
                            kind={modalKind}
                            integration={integrationKind || undefined}
                            onComplete={handleModalComplete}
                            onClose={closeNewIntegrationModal}
                        />
                    )
                })}
        </>
    )
}
