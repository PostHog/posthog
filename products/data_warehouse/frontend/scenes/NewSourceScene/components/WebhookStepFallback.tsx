import { useActions, useValues } from 'kea'

import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { sourceWizardLogic } from '../sourceWizardLogic'

/** The ways out of the wizard's webhook step when the webhook is not set up yet. */
export function WebhookStepFallback({ webhookTableCount }: { webhookTableCount: number }): JSX.Element | null {
    const {
        selectedConnector,
        webhookCreating,
        webhookStepComplete,
        webhookNeedsManualConfirmation,
        webhookManualSetupConfirmed,
        webhookTablesSwitching,
    } = useValues(sourceWizardLogic)
    const { setWebhookManualSetupConfirmed, switchWebhookTablesToPolling, skipWebhookSetup } =
        useActions(sourceWizardLogic)

    const sourceName = selectedConnector?.label ?? selectedConnector?.name ?? 'the source'

    if (webhookCreating) {
        return null
    }

    return (
        <div className="flex flex-col gap-4">
            {webhookNeedsManualConfirmation && (
                <LemonCheckbox
                    checked={webhookManualSetupConfirmed}
                    onChange={setWebhookManualSetupConfirmed}
                    label={`I added the webhook URL in ${sourceName}`}
                    bordered
                    data-attr="source-wizard-webhook-manual-confirm"
                />
            )}
            {!webhookStepComplete && (
                <LemonCard hoverEffect={false} className="flex flex-col gap-3">
                    <h4 className="font-semibold mb-0">Can't set up the webhook now?</h4>
                    <p className="mb-0">
                        {webhookTableCount.toLocaleString()} {webhookTableCount === 1 ? 'table uses' : 'tables use'}{' '}
                        webhook sync. Without a working webhook, each sync of these tables reads the {sourceName} API
                        instead. This is slower, and a sync can read the whole table each time.
                    </p>
                    <p className="mb-0">
                        Change these tables to incremental sync where {sourceName} supports it, and to full refresh
                        where it doesn't. You can switch them back to webhook sync later.
                    </p>
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={switchWebhookTablesToPolling}
                            loading={webhookTablesSwitching}
                            data-attr="source-wizard-webhook-switch-sync-method"
                        >
                            Use another sync method
                        </LemonButton>
                        <LemonButton
                            type="tertiary"
                            status="danger"
                            onClick={skipWebhookSetup}
                            disabledReason={webhookTablesSwitching ? 'Changing the sync method' : undefined}
                            data-attr="source-wizard-webhook-skip"
                        >
                            Skip for now
                        </LemonButton>
                    </div>
                </LemonCard>
            )}
        </div>
    )
}
