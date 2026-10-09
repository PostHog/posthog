import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconCollapse, IconExpand, IconGear, IconLetter, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

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
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const defaultSenderId = currentTeam?.workflows_config?.default_email_integration_id ?? null

    const makeDefault = (integrationId: number): void => {
        updateCurrentTeam({
            workflows_config: { ...currentTeam?.workflows_config, default_email_integration_id: integrationId },
        })
        // pinned: analytics event name
        posthog.capture('workflows default email sender set', { had_default: defaultSenderId !== null })
    }
    const { domain, integrations } = integration
    const verified = integrations.every(isVerified)
    const verificationRequired = integrations.some(isVerificationRequired)
    const [isExpanded, setIsExpanded] = useState(false)

    return (
        <div className="rounded border bg-surface-primary">
            <div
                className="flex flex-1 justify-between items-center p-2 cursor-pointer"
                onClick={() => setIsExpanded(!isExpanded)}
            >
                <div className="flex flex-1 gap-4 items-center ml-2">
                    <IconLetter className="w-8 h-8" />
                    <div className="flex-1">
                        <div className="flex gap-2 items-center">
                            <span>
                                <strong>{domain}</strong>
                            </span>
                            <span className="text-xs text-secondary">
                                {integrations.length} {integrations.length === 1 ? 'sender' : 'senders'}
                            </span>
                            {integrations.some((sender) => sender.id === defaultSenderId) && (
                                <LemonTag type="primary">Default sender</LemonTag>
                            )}
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
                    <div className="text-secondary">
                        {isExpanded ? <IconCollapse className="text-lg" /> : <IconExpand className="text-lg" />}
                    </div>
                </div>
            </div>

            {isExpanded && (
                <div className="flex flex-col">
                    {integrations.map((integration) => (
                        <div key={integration.id} className="flex items-center px-4 py-2 border-t gap-2">
                            <span className="flex-1">
                                {integration.config.name} &lt;{integration.config.email}&gt;
                            </span>
                            {integration.id === defaultSenderId ? (
                                <Tooltip title="New broadcasts and workflow emails start with this sender">
                                    <LemonTag type="primary" data-attr="email-sender-default-tag">
                                        Default
                                    </LemonTag>
                                </Tooltip>
                            ) : isVerified(integration) ? (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={() => makeDefault(integration.id)}
                                    disabledReason={currentTeamLoading ? 'Saving…' : undefined}
                                    data-attr="email-sender-make-default"
                                >
                                    Make default
                                </LemonButton>
                            ) : null}
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={() => {
                                    openSetupModal(integration, integration.kind as ChannelType)
                                }}
                                icon={<IconGear />}
                            >
                                Configure
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                size="small"
                                status="danger"
                                onClick={() => {
                                    deleteIntegration(integration.id)
                                }}
                                icon={<IconTrash />}
                            >
                                Disconnect
                            </LemonButton>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
