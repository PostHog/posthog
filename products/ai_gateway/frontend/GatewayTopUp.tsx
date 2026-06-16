import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { humanFriendlyCurrency } from 'lib/utils'

import { aiGatewayLogic } from './aiGatewayLogic'

// Placeholder balance: the gateway has no balance endpoint yet (products/ai_gateway/backend/routes.py
// is an empty stub), so this is a frontend mock until that lands.
const MOCK_BALANCE_USD = 42.5

const TOP_UP_PRESETS_USD = [25, 50, 100, 250]

export function GatewayBalanceCard(): JSX.Element {
    const { openTopUpModal } = useActions(aiGatewayLogic)

    return (
        <div className="border rounded p-4 min-w-48 flex-1 flex items-center justify-between gap-4">
            <div>
                <div className="text-secondary text-xs uppercase">Balance</div>
                <div className="text-2xl font-semibold">{humanFriendlyCurrency(MOCK_BALANCE_USD)}</div>
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
