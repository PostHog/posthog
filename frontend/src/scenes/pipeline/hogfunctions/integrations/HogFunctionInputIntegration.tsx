import { LemonButton, LemonMenu, LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IconSlack } from 'lib/lemon-ui/icons'

import { HogFunctionInputSchemaType } from '~/types'

export type HogFunctionInputIntegrationConfigureProps = {
    value?: any
    onChange?: (value: string | null) => void
}

export type HogFunctionInputIntegrationProps = HogFunctionInputIntegrationConfigureProps & {
    schema: HogFunctionInputSchemaType
}

export function HogFunctionInputIntegration({ schema, ...props }: HogFunctionInputIntegrationProps): JSX.Element {
    if (schema.integration === 'slack') {
        return <HogFunctionIntegrationSlackConnection {...props} />
    }
    return (
        <div className="text-danger">
            <p>Unsupported integration type: {schema.integration}</p>
        </div>
    )
}

export function HogFunctionIntegrationSlackConnection({
    onChange,
    value,
}: HogFunctionInputIntegrationConfigureProps): JSX.Element {
    const { integrationsLoading, slackIntegrations, addToSlackButtonUrl } = useValues(integrationsLogic)

    const integration = slackIntegrations?.find((integration) => `${integration.id}` === value)

    if (integrationsLoading) {
        return <LemonSkeleton className="h-10" />
    }

    const button = (
        <LemonMenu
            items={[
                ...(slackIntegrations?.map((integration) => ({
                    icon: <IconSlack />,
                    onClick: () => onChange?.(`${integration.id}`),
                    label: integration.config.team.name,
                })) || []),
                {
                    to: addToSlackButtonUrl(window.location.pathname + '?target_type=slack') || '',
                    label: 'Add to different Slack workspace',
                },
            ]}
        >
            {integration ? (
                <LemonButton type="secondary">Change</LemonButton>
            ) : (
                <LemonButton type="secondary"> Choose Slack connection</LemonButton>
            )}
        </LemonMenu>
    )

    return (
        <>
            {integration ? (
                <div className="rounded border flex justify-between items-center p-2 bg-bg-light">
                    <div className="flex items-center gap-4 ml-2">
                        <IconSlack className="text-2xl" />
                        <div>
                            <div>
                                Connected to <strong>{integration.config.team.name}</strong> workspace
                            </div>
                            {integration.created_by ? (
                                <UserActivityIndicator
                                    at={integration.created_at}
                                    by={integration.created_by}
                                    prefix="Updated"
                                    className="text-muted"
                                />
                            ) : null}
                        </div>
                    </div>

                    {button}
                </div>
            ) : (
                button
            )}
        </>
    )
}
