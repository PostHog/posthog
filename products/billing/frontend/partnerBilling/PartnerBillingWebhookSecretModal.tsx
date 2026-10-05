import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'

import { PartnerBillingLogicProps, partnerBillingLogic } from './partnerBillingLogic'

export function PartnerBillingWebhookSecretModal({ applicationId }: PartnerBillingLogicProps): JSX.Element {
    const logic = partnerBillingLogic({ applicationId })
    const { webhookSecret } = useValues(logic)
    const { dismissWebhookSecret } = useActions(logic)

    return (
        <LemonModal
            isOpen={!!webhookSecret}
            onClose={dismissWebhookSecret}
            closable={false}
            title="Your signing secret"
            footer={
                <LemonButton
                    type="primary"
                    onClick={dismissWebhookSecret}
                    data-attr="partner-billing-dismiss-webhook-secret"
                >
                    I've copied it
                </LemonButton>
            }
        >
            {webhookSecret && (
                <div className="flex flex-col gap-3">
                    <LemonBanner type="warning">
                        Copy this secret now. PostHog won't show it again, so if you lose it you need to rotate it.
                    </LemonBanner>
                    <p className="mb-0">
                        Use it to verify the signature on every billing event PostHog sends to your webhook URL.
                    </p>
                    <CodeSnippet thing="signing secret">{webhookSecret.secret}</CodeSnippet>
                </div>
            )}
        </LemonModal>
    )
}
