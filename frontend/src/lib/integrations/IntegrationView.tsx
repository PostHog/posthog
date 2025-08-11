import { IconWarning, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import api from 'lib/api'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { IntegrationScopesWarning } from 'lib/integrations/IntegrationScopesWarning'
import { ChannelType } from 'products/messaging/frontend/Channels/MessageChannels'

import { CyclotronJobInputSchemaType, IntegrationType } from '~/types'
import { integrationsLogic } from './integrationsLogic'

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

export function IntegrationView({
    integration,
    suffix,
    schema,
}: {
    integration: IntegrationType
    suffix?: JSX.Element
    schema?: CyclotronJobInputSchemaType
}): JSX.Element {
    const { deleteIntegration, openSetupModal } = useActions(integrationsLogic)

    const errors = (integration.errors && integration.errors?.split(',')) || []
    const verified = isVerified(integration)
    const verificationRequired = isVerificationRequired(integration)

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

    suffix = suffix || (
        <div className="flex flex-row gap-2">
            {!isVerified(integration) && (
                <LemonButton
                    type="primary"
                    onClick={() => {
                        openSetupModal(integration, integration.kind as ChannelType)
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
    )

    return (
        <div className="rounded border bg-surface-primary">
            <div className="flex justify-between items-center p-2">
                <div className="flex gap-4 items-center ml-2">
                    <img src={integration.icon_url} className="w-10 h-10 rounded" />
                    <div>
                        <div className="flex gap-2">
                            <span>
                                Connected to <strong>{integration.display_name}</strong>
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
                        {integration.created_by ? (
                            <UserActivityIndicator
                                at={integration.created_at}
                                by={integration.created_by}
                                prefix="Updated"
                                className="text-secondary"
                            />
                        ) : null}
                    </div>
                </div>

                {suffix}
            </div>

            {errors.length > 0 ? (
                <div className="p-2">
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Reconnect',
                            disableClientSideRouting: true,
                            to: api.integrations.authorizeUrl({
                                kind: integration.kind,
                                next: window.location.pathname,
                            }),
                        }}
                    >
                        {errors[0] === 'TOKEN_REFRESH_FAILED'
                            ? 'Authentication token could not be refreshed. Please reconnect.'
                            : `There was an error with this integration: ${errors[0]}`}
                    </LemonBanner>
                </div>
            ) : (
                <IntegrationScopesWarning integration={integration} schema={schema} />
            )}
        </div>
    )
}
