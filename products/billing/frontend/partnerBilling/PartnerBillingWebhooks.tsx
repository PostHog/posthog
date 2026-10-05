import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonDialog, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { PartnerBillingLogicProps, partnerBillingLogic } from './partnerBillingLogic'
import { PartnerBillingWebhookSecretModal } from './PartnerBillingWebhookSecretModal'

export function PartnerBillingWebhooks({ applicationId }: PartnerBillingLogicProps): JSX.Element {
    const logic = partnerBillingLogic({ applicationId })
    const { payer, isWebhookFormSubmitting, webhookFormHasChanges, webhookSecretLoading, testEventLoading } =
        useValues(logic)
    const { rotatePartnerBillingWebhookSecret, sendPartnerBillingTestEvent } = useActions(logic)
    const savedWebhookUrl = payer?.webhook?.url
    const secretCreatedAt = payer?.webhook?.secret_created_at

    const createSigningSecret = (): void => {
        if (!secretCreatedAt) {
            rotatePartnerBillingWebhookSecret()
            return
        }
        LemonDialog.open({
            title: 'Rotate the signing secret?',
            description:
                'The current secret stops signing events as soon as the new one exists. Update your endpoint to verify events with the new secret.',
            primaryButton: {
                children: 'Rotate signing secret',
                status: 'danger',
                onClick: () => rotatePartnerBillingWebhookSecret(),
                'data-attr': 'partner-billing-confirm-rotate-webhook-secret',
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <section className="flex flex-col gap-4">
            <div>
                <h3 className="text-base font-semibold mb-1">Webhooks</h3>
                <p className="text-secondary text-sm mb-0">
                    PostHog sends billing events for the organizations you pay for to this URL, signed with your signing
                    secret.
                </p>
            </div>
            <Form
                logic={partnerBillingLogic}
                props={{ applicationId }}
                formKey="webhookForm"
                enableFormOnSubmit
                className="flex flex-col gap-2 max-w-120"
            >
                <LemonField name="webhook_url" label="Webhook URL" help="Leave it empty to stop sending events.">
                    <LemonInput
                        placeholder="https://example.com/webhooks/posthog"
                        data-attr="partner-billing-webhook-url"
                    />
                </LemonField>
                <div>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isWebhookFormSubmitting}
                        disabledReason={!webhookFormHasChanges ? 'No changes to save' : undefined}
                        data-attr="partner-billing-save-webhook-url"
                    >
                        Save
                    </LemonButton>
                </div>
            </Form>
            <div className="flex flex-col gap-2">
                <LemonLabel>Signing secret</LemonLabel>
                <p className="text-sm mb-0">
                    {secretCreatedAt ? (
                        <span>
                            Created <TZLabel time={secretCreatedAt} />
                        </span>
                    ) : (
                        <span>No signing secret yet.</span>
                    )}
                </p>
                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={createSigningSecret}
                        loading={webhookSecretLoading}
                        data-attr="partner-billing-rotate-webhook-secret"
                    >
                        {secretCreatedAt ? 'Rotate signing secret' : 'Generate signing secret'}
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        onClick={() => sendPartnerBillingTestEvent()}
                        loading={testEventLoading}
                        disabledReason={
                            !savedWebhookUrl
                                ? 'Save a webhook URL first'
                                : !secretCreatedAt
                                  ? 'Generate a signing secret first'
                                  : undefined
                        }
                        data-attr="partner-billing-send-test-event"
                    >
                        Send test event
                    </LemonButton>
                </div>
            </div>
            <PartnerBillingWebhookSecretModal applicationId={applicationId} />
        </section>
    )
}
