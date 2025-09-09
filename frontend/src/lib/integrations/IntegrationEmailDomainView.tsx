import { useActions } from 'kea'

import { IconLetter, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { EmailIntegrationDomainGroupedType, IntegrationType } from '~/types'

import { ChannelType } from 'products/messaging/frontend/Channels/MessageChannels'

import { integrationsLogic } from './integrationsLogic'

const isVerificationRequired = (integration: IntegrationType): boolean => {
    return ['email'].includes(integration.kind)
}

const isGroupVerified = (integration: IntegrationType): boolean => {
    switch (integration.kind) {
        case 'email':
            return integration.config.mailjet_verified === true
        default:
            return true
    }
}

const isSenderVerified = (integration: IntegrationType): boolean => {
    switch (integration.kind) {
        case 'email':
            return integration.config.mailjet_email_address_verified === true
        default:
            return true
    }
}

export function IntegrationEmailDomainView({
    integration,
}: {
    integration: EmailIntegrationDomainGroupedType
}): JSX.Element {
    const { openSetupModal, deleteIntegration, reverifyEmailIntegration } = useActions(integrationsLogic)
    const { domain, integrations } = integration
    const groupVerified = integrations.every(isGroupVerified)
    const verificationRequired = integrations.some(isVerificationRequired)

    return (
        <div className="rounded border bg-surface-primary">
            <div className="flex flex-1 justify-between items-center p-2">
                <div className="flex flex-1 gap-4 items-center ml-2">
                    <IconLetter className="w-8 h-8" />
                    <div className="flex-1">
                        <div className="flex gap-2">
                            <span>
                                <strong>{domain}</strong>
                            </span>
                            {verificationRequired && (
                                <Tooltip
                                    title={
                                        groupVerified
                                            ? 'This channel is ready to use'
                                            : 'You cannot send messages from this domain until it has been verified'
                                    }
                                >
                                    <LemonTag type={groupVerified ? 'success' : 'warning'}>
                                        {groupVerified ? 'Verified' : 'Unverified'}
                                    </LemonTag>
                                </Tooltip>
                            )}
                        </div>
                    </div>
                    {verificationRequired && !groupVerified && (
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => {
                                openSetupModal(integrations[0], integrations[0].kind as ChannelType)
                            }}
                            icon={<IconWarning />}
                        >
                            Verify
                        </LemonButton>
                    )}
                </div>
            </div>

            <div className="flex flex-col">
                {integrations.map((integration) => (
                    <div key={integration.id} className="flex items-center px-4 py-2 border-t">
                        <div className="flex gap-2 flex-1">
                            <span>
                                {integration.config.name} &lt;{integration.config.email}&gt;
                            </span>
                            <Tooltip
                                title={
                                    isSenderVerified(integration)
                                        ? 'This sender is ready to use'
                                        : 'You cannot send messages from this address until it has been verified. Check your email for a verification link or send a new one.'
                                }
                            >
                                <LemonTag type={isSenderVerified(integration) ? 'success' : 'warning'}>
                                    {isSenderVerified(integration) ? 'Verified' : 'Unverified'}
                                </LemonTag>
                            </Tooltip>

                            {!isSenderVerified(integration) && (
                                <LemonButton
                                    type="primary"
                                    size="xsmall"
                                    icon={<IconRefresh />}
                                    onClick={() => {
                                        void reverifyEmailIntegration(integration.id)
                                    }}
                                >
                                    Re-verify email
                                </LemonButton>
                            )}
                        </div>
                        <LemonButton
                            size="small"
                            status="danger"
                            onClick={() => {
                                deleteIntegration(integration.id)
                            }}
                        >
                            Remove
                        </LemonButton>
                    </div>
                ))}
            </div>
        </div>
    )
}
