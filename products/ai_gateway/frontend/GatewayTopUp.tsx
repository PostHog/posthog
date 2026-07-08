import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonTag } from '@posthog/lemon-ui'

import { humanFriendlyCurrency } from 'lib/utils/numbers'

import { aiGatewayLogic } from './aiGatewayLogic'

const TOP_UP_PRESETS_USD = [25, 50, 100, 250]

// The gateway has no balance endpoint yet (products/ai_gateway/backend/routes.py is an empty
// stub), so the balance is shown as a Preview placeholder until that lands.
export function GatewayBalanceCard(): JSX.Element {
    const { openTopUpModal } = useActions(aiGatewayLogic)

    return (
        <div className="border rounded p-4 min-w-48 flex-1 flex items-center justify-between gap-4">
            <div>
                <div className="text-secondary text-xs uppercase flex items-center gap-1.5">
                    Balance
                    <LemonTag type="warning">Preview</LemonTag>
                </div>
                <div className="text-2xl font-semibold">—</div>
            </div>
            <LemonButton type="primary" onClick={openTopUpModal}>
                Top up
            </LemonButton>
        </div>
    )
}

export function GatewayTopUpModal(): JSX.Element {
    const { isTopUpModalOpen, topUpAmountUsd } = useValues(aiGatewayLogic)
    const { closeTopUpModal, setTopUpAmount, confirmTopUp } = useActions(aiGatewayLogic)

    return (
        <LemonModal
            isOpen={isTopUpModalOpen}
            onClose={closeTopUpModal}
            title="Top up balance"
            description="Add funds to cover gateway usage — you're billed at cost, no markup on tokens."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeTopUpModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={confirmTopUp}
                        disabledReason={topUpAmountUsd <= 0 ? 'Enter an amount' : undefined}
                    >
                        Top up {humanFriendlyCurrency(topUpAmountUsd)}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3 max-w-md">
                <LemonBanner type="info">Preview only — billing isn't wired up yet.</LemonBanner>
                <div className="flex gap-2 flex-wrap">
                    {TOP_UP_PRESETS_USD.map((amount) => (
                        <LemonButton
                            key={amount}
                            type={topUpAmountUsd === amount ? 'primary' : 'secondary'}
                            onClick={() => setTopUpAmount(amount)}
                        >
                            {humanFriendlyCurrency(amount, 0)}
                        </LemonButton>
                    ))}
                </div>
                <LemonInput
                    type="number"
                    value={topUpAmountUsd}
                    onChange={(value) => setTopUpAmount(value ?? 0)}
                    prefix={<span className="text-secondary">$</span>}
                    min={0}
                />
            </div>
        </LemonModal>
    )
}
