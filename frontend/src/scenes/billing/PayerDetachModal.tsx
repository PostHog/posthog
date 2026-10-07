import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { payerDetachLogic } from './payerDetachLogic'

export function PayerDetachModal(): JSX.Element | null {
    const { isPayerDetachModalOpen, isDetachingFromPayer, payerDetachError, billingPartnerName } =
        useValues(payerDetachLogic)
    const { closePayerDetachModal, detachFromPayer } = useActions(payerDetachLogic)

    if (!billingPartnerName) {
        return null
    }

    return (
        <LemonModal
            isOpen={isPayerDetachModalOpen}
            onClose={closePayerDetachModal}
            closable={!isDetachingFromPayer}
            title="Pay for this organization yourself?"
            width={520}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={() => closePayerDetachModal()}
                        disabled={isDetachingFromPayer}
                        data-attr="billing-payer-detach-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => detachFromPayer()}
                        loading={isDetachingFromPayer}
                        data-attr="billing-payer-detach-confirm"
                    >
                        Pay for it myself
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                {payerDetachError && <LemonBanner type="error">{payerDetachError}</LemonBanner>}
                <p className="mb-0">When you confirm:</p>
                <ul className="list-disc pl-6 mb-0 space-y-1">
                    <li>{`${billingPartnerName} pays for this organization's usage until billing confirms the change.`}</li>
                    <li>From then on, this organization pays for its own usage and needs its own payment method.</li>
                    <li>
                        Until you add a payment method, the organization is on the free plan and free tier limits apply.
                    </li>
                    <li>{`${billingPartnerName} keeps its current access to this organization's projects.`}</li>
                </ul>
                <p className="mb-0">You can't undo this.</p>
            </div>
        </LemonModal>
    )
}
