import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconExternal, IconTrash, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu, LemonSkeleton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { getIntegrationNameFromKind } from 'lib/integrations/utils'
import { urls } from 'scenes/urls'

import { findIntegrationByFormValue, matchesIntegrationIdValue } from './integrationLookup'
import { getAllRegisteredIntegrationSetups, getIntegrationSetup } from './integrationSetupRegistry'

// Side-effect import: register all integration setups
import './integrationSetups'

export type IntegrationConfigureProps = {
    value?: number
    onChange?: (value: number | null) => void
    redirectUrl?: string
    schema?: { requiredScopes?: string }
    integration?: string
    beforeRedirect?: () => void
    autoSelectFirstIntegration?: boolean
}

export function IntegrationChoice({
    onChange,
    value,
    schema,
    integration,
    redirectUrl,
    beforeRedirect,
    autoSelectFirstIntegration = true,
}: IntegrationConfigureProps): JSX.Element | null {
    const { integrationsLoading, integrations, newIntegrationModalKind, slackAvailable } = useValues(integrationsLogic)
    const { newGoogleCloudKey, openNewIntegrationModal, closeNewIntegrationModal, deleteIntegration } =
        useActions(integrationsLogic)
    const kind = integration

    const integrationsOfKind = integrations?.filter((x) => x.kind === kind)
    const integrationKind = findIntegrationByFormValue(integrationsOfKind, value)

    // The stored value points to an integration that's no longer available (deleted, or
    // re-installed under a new ID). We deliberately do NOT auto-substitute here — that
    // would silently mask the missing reference and let stale config keep flowing through
    // saves. The UI surfaces a warning below instead so the user picks explicitly.
    const valueIsMissing = !integrationsLoading && !!value && !!integrations && !integrationKind

    // Fire at most once: the consumer's write may take a full state round-trip before it flows
    // back into `value`, and re-dispatching on every render in that window can amplify into an
    // infinite update loop (React #185).
    const autoSelected = useRef(false)
    useEffect(() => {
        if (autoSelectFirstIntegration && !integrationsLoading && !value && integrationsOfKind?.length && !autoSelected.current) {
            autoSelected.current = true
            onChange?.(integrationsOfKind[0].id)
        }
    }, [
        autoSelectFirstIntegration,
        integrationsLoading,
        onChange,
        integrationsOfKind?.length,
        value,
        integrationsOfKind,
    ])

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
    // When the instance doesn't have OAuth credentials for this kind, /integrations/authorize
    // 400s with "Kind not configured". Send users to the settings page instead.
    const oauthUnavailable = kind === 'slack' && !slackAvailable
    const setupMenuItem = setupDef
        ? setupDef.menuItem({ kind, openModal: openNewIntegrationModal, uploadKey })
        : oauthUnavailable
          ? {
                to: urls.settings('project-integrations'),
                sideIcon: <IconExternal />,
                label: `${kindName} is not configured on this instance`,
            }
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
                                  icon: (
                                      <img
                                          src={integ.icon_url}
                                          alt={`${integ.display_name} icon`}
                                          className="w-6 h-6 rounded"
                                      />
                                  ),
                                  onClick: () => onChange?.(integ.id),
                                  active: matchesIntegrationIdValue(integ.id, value),
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
                                  label: 'Clear selection',
                                  sideIcon: <IconX />,
                              }
                            : null,
                        integrationKind
                            ? {
                                  onClick: () => {
                                      deleteIntegration(integrationKind.id)
                                  },
                                  label: 'Disconnect integration',
                                  status: 'danger' as const,
                                  sideIcon: <IconTrash />,
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
            ) : valueIsMissing ? (
                <div className="flex flex-col gap-2">
                    <LemonBanner type="warning">
                        The previously selected {kindName} connection (ID: {value}) is no longer available. Pick a
                        different connection or clear the selection — this connection will fail at runtime otherwise.
                    </LemonBanner>
                    {button}
                </div>
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
