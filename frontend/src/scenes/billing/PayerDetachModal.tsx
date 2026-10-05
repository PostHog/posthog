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
                    <li>{`From now on, ${billingPartnerName} stops paying for this organization.`}</li>
                    <li>{`Usage so far this month stays on ${billingPartnerName}'s bill.`}</li>
                    <li>This organization then needs its own payment method, like any other organization.</li>
                </ul>
                <p className="mb-0">You can't undo this.</p>
            </div>
        </LemonModal>
    )
}
