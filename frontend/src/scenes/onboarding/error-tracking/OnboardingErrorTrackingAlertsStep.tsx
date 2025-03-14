import { LemonButton, LemonButtonProps, LemonInput, LemonTable, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { HogFunctionIcon } from 'scenes/pipeline/hogfunctions/HogFunctionIcon'

import { IntegrationType } from '~/types'

import { type OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import {
    ErrorTrackingAlertIntegrationType,
    onboardingErrorTrackingAlertsLogic,
} from './onboardingErrorTrackingAlertsStepLogic'

export function OnboardingErrorTrackingAlertsStep({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element {
    const { slackIntegrations, slackAvailable } = useValues(integrationsLogic)
    const { integration } = useValues(onboardingErrorTrackingAlertsLogic)
    const { setIntegration } = useActions(onboardingErrorTrackingAlertsLogic)

    const dataSource = [
        {
            key: 'teams',
            name: 'Microsoft Teams',
            icon: '/static/services/microsoft-teams.png',
            action: <ConnectButton onClick={() => setIntegration('teams')} />,
        },
        {
            key: 'discord',
            name: 'Discord',
            icon: '/static/services/discord.png',
            action: <ConnectButton onClick={() => setIntegration('discord')} />,
        },
    ]

    if (slackAvailable) {
        dataSource.unshift({
            key: 'slack',
            name: 'Slack',
            icon: '/static/services/slack.png',
            action:
                slackIntegrations && slackIntegrations.length > 0 ? (
                    <ConnectButton onClick={() => setIntegration('slack')} />
                ) : (
                    <ConnectButton
                        to={api.integrations.authorizeUrl({
                            kind: 'slack',
                            next: '/onboarding/error_tracking?step=alerts&kind=slack_callback',
                        })}
                    />
                ),
        })
    }

    return (
        <OnboardingStep title="Configure alerts" stepKey={stepKey} continueOverride={<></>} showSkip={!integration}>
            <p>Choose a destination for new issues to be sent</p>
            {integration === null ? (
                <LemonTable
                    showHeader={false}
                    columns={[
                        {
                            key: 'name',
                            dataIndex: 'name',
                            render: (_, record) => {
                                return (
                                    <div className="flex gap-2 font-bold items-center">
                                        <HogFunctionIcon size="small" src={record.icon} />
                                        {record.name}
                                    </div>
                                )
                            },
                        },
                        {
                            key: 'actions',
                            width: 0,
                            render: (_, record) => record.action,
                        },
                    ]}
                    dataSource={dataSource}
                />
            ) : (
                <div className="flex flex-col gap-2">
                    <Form enableFormOnSubmit logic={onboardingErrorTrackingAlertsLogic} formKey="connectionConfig">
                        <FormFields
                            integration={integration}
                            slackIntegration={slackIntegrations ? slackIntegrations[0] : undefined}
                        />
                        <div className="flex justify-end gap-2">
                            <LemonButton center type="secondary" onClick={() => setIntegration(null)}>
                                Back
                            </LemonButton>
                            <LemonButton type="primary" center htmlType="submit">
                                Next
                            </LemonButton>
                        </div>
                    </Form>
                </div>
            )}
        </OnboardingStep>
    )
}

const FormFields = ({
    integration,
    slackIntegration,
}: {
    integration: ErrorTrackingAlertIntegrationType
    slackIntegration?: IntegrationType
}): JSX.Element | null => {
    return integration === 'discord' ? (
        <LemonField
            name="discordWebhookUrl"
            label="Webhook URL"
            help={
                <p className="text-secondary text-xs">
                    See this page on how to generate a Webhook URL:
                    <Link to="https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks">
                        https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks
                    </Link>
                </p>
            }
        >
            <LemonInput />
        </LemonField>
    ) : integration === 'teams' ? (
        <LemonField
            name="teamsWebhookUrl"
            label="Webhook URL"
            help={
                <p className="text-secondary text-xs">
                    See this page on how to generate a Webhook URL:
                    <Link to="https://support.microsoft.com/en-us/office/create-incoming-webhooks-with-workflows-for-microsoft-teams-8ae491c7-0394-4861-ba59-055e33f75498">
                        https://support.microsoft.com/en-us/office/create-incoming-webhooks-with-workflows-for-microsoft-teams-8ae491c7-0394-4861-ba59-055e33f75498
                    </Link>
                </p>
            }
        >
            <LemonInput />
        </LemonField>
    ) : integration === 'slack' && slackIntegration ? (
        <LemonField name="slackChannelId" label="Channel">
            <SlackChannelPicker integration={slackIntegration} />
        </LemonField>
    ) : null
}

const ConnectButton = (buttonProps: Pick<LemonButtonProps, 'onClick' | 'to'>): JSX.Element => (
    <LemonButton {...buttonProps} className="py-1" fullWidth type="primary" size="small">
        Connect
    </LemonButton>
)
