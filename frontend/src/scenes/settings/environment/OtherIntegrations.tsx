import { IconTrash, IconWarning } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { ChannelSetupModal } from 'products/messaging/frontend/Channels/ChannelSetupModal'
import { ChannelType } from 'products/messaging/frontend/Channels/messageChannelsLogic'

import { IntegrationKind, IntegrationType } from '~/types'

export function OtherIntegrations({
    integrationKinds,
    titleText = 'All connected integrations are listed here. These integrations may be used for various purposes, such as data warehouse or pipeline destinations. To connect a new integration, visit the relevant product area.',
}: {
    integrationKinds: IntegrationKind[]
    titleText?: string
}): JSX.Element {
    const { integrations, integrationsLoading, setupModalOpen } = useValues(integrationsLogic)
    const { deleteIntegration, openSetupModal, closeSetupModal } = useActions(integrationsLogic)

    const otherIntegrations = integrations?.filter((integration) => integrationKinds.includes(integration.kind))

    const onDeleteClick = (integration: IntegrationType): void => {
        LemonDialog.open({
            title: `Do you want to disconnect from this ${integration.kind} integration?`,
            description:
                'This cannot be undone. PostHog resources configured to use this integration will remain but will stop working.',
            primaryButton: {
                children: 'Yes, disconnect',
                status: 'danger',
                onClick: () => deleteIntegration(integration.id),
            },
            secondaryButton: {
                children: 'No thanks',
            },
        })
    }

    const isVerificationRequired = (integration: IntegrationType): boolean => {
        return ['email'].includes(integration.kind)
    }

    const isVerified = (integration: IntegrationType): boolean => {
        switch (integration.kind) {
            case 'email':
                return integration.config.mailjet_verified === true
            default:
                return true
        }
    }

    return (
        <div>
            {titleText ? <p>{titleText}</p> : null}

            <div className="deprecated-space-y-2">
                {otherIntegrations?.length ? (
                    otherIntegrations.map((integration) => (
                        <>
                            <IntegrationView
                                key={integration.id}
                                integration={integration}
                                isVerified={isVerified(integration)}
                                isVerificationRequired={isVerificationRequired(integration)}
                                suffix={
                                    <div className="flex flex-row gap-2">
                                        {!isVerified(integration) && (
                                            <LemonButton
                                                type="primary"
                                                onClick={() => {
                                                    openSetupModal(integration.id)
                                                }}
                                                icon={<IconWarning />}
                                            >
                                                Verify
                                            </LemonButton>
                                        )}
                                        <LemonButton
                                            type="secondary"
                                            status="danger"
                                            onClick={() => onDeleteClick(integration)}
                                            icon={<IconTrash />}
                                        >
                                            Disconnect
                                        </LemonButton>
                                    </div>
                                }
                            />
                            {setupModalOpen === integration.id && (
                                <ChannelSetupModal
                                    isOpen={setupModalOpen === integration.id}
                                    channelType={integration.kind as ChannelType}
                                    integration={integration}
                                    onComplete={closeSetupModal}
                                />
                            )}
                        </>
                    ))
                ) : integrationsLoading ? (
                    <LemonSkeleton className="h-10" />
                ) : (
                    <p>No integrations</p>
                )}
            </div>
        </div>
    )
}
