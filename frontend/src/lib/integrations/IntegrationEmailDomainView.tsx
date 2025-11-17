import { useActions } from 'kea'

import { IconLetter, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { EmailIntegrationDomainGroupedType, IntegrationType } from '~/types'

import { ChannelType } from 'products/workflows/frontend/Channels/MessageChannels'

import { integrationsLogic } from './integrationsLogic'

const isVerificationRequired = (integration: IntegrationType): boolean => {
    return ['email'].includes(integration.kind)
}

const isVerified = (integration: IntegrationType): boolean => {
    switch (integration.kind) {
        case 'email':
            return integration.config.verified === true
        default:
            return true
    }
}

export function IntegrationEmailDomainView({
    integration,
}: {
    integration: EmailIntegrationDomainGroupedType
}): JSX.Element {
    const { openSetupModal, deleteIntegration } = useActions(integrationsLogic)
    const { domain, integrations } = integration
    const verified = integrations.every(isVerified)
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
                                        verified
                                            ? 'This channel is ready to use'
                                            : 'You cannot send messages from this channel until it has been verified'
                                    }
                                >
                                    <LemonTag type={verified ? 'success' : 'warning'}>
                                        {verified ? 'Verified' : 'Unverified'}
                                    </LemonTag>
                                </Tooltip>
                            )}
                        </div>
                    </div>
                    {verificationRequired && !verified && (
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
                        <span className="flex-1">
                            {integration.config.name} &lt;{integration.config.email}&gt;
                        </span>
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
