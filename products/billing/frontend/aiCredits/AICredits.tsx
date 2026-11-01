import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { AddAICreditsModal } from './AddAICreditsModal'
import { AICreditHistory } from './AICreditHistory'
import { aiCreditsLogic } from './aiCreditsLogic'
import { AISpendSettingsModal } from './AISpendSettingsModal'
import { BalanceTile } from './BalanceTile'
import { BillingPeriodSpendTile } from './BillingPeriodSpendTile'
import { DailyAverageTile } from './DailyAverageTile'
import { DailySpendChart } from './DailySpendChart'
import { ProductSpendTable } from './ProductSpendTable'

export function AICredits(): JSX.Element {
    const { unavailable, spend, spendUnavailable, spendProducts, periodOptions, selectedPeriodsAgo } =
        useValues(aiCreditsLogic)
    const { openAddFundsModal, selectPeriod } = useActions(aiCreditsLogic)

    if (unavailable) {
        return <LemonBanner type="info">AI credits aren't available for this organization yet.</LemonBanner>
    }

    return (
        <div className="@container/ai-credits flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                {periodOptions.length > 0 ? (
                    <LemonSelect
                        size="small"
                        value={selectedPeriodsAgo}
                        onChange={selectPeriod}
                        options={periodOptions.map((option) => ({ value: option.periodsAgo, label: option.label }))}
                        dropdownMatchSelectWidth={false}
                        data-attr="ai-credits-period"
                    />
                ) : (
                    <span />
                )}
                <LemonButton type="primary" onClick={openAddFundsModal} data-attr="ai-credits-add-funds">
                    Add funds
                </LemonButton>
            </div>
            <div className="grid gap-4 @min-[56rem]/ai-credits:grid-cols-3">
                <BillingPeriodSpendTile />
                <DailyAverageTile />
                <BalanceTile />
            </div>
            {spend ? (
                <>
                    <DailySpendChart spend={spend} products={spendProducts} />
                    <ProductSpendTable spend={spend} products={spendProducts} />
                </>
            ) : (
                !spendUnavailable && <LemonSkeleton className="h-80" />
            )}
            <AICreditHistory />
            <AddAICreditsModal />
            <AISpendSettingsModal />
        </div>
    )
}
