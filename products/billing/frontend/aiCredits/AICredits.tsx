import { useActions, useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { AddAICreditsModal } from './AddAICreditsModal'
import { AICreditHistory } from './AICreditHistory'
import { aiCreditsLogic } from './aiCreditsLogic'
import { AISpendSettingsModal } from './AISpendSettingsModal'
import { BalanceTile } from './BalanceTile'
import { DailyAverageTile } from './DailyAverageTile'
import { DailySpendChart } from './DailySpendChart'
import { ProductSpendTable } from './ProductSpendTable'
import { SpendThisPeriodTile } from './SpendThisPeriodTile'

export function AICredits(): JSX.Element {
    const { unavailable, spend, spendSummary, spendUnavailable, spendProducts } = useValues(aiCreditsLogic)
    const { openAddFundsModal } = useActions(aiCreditsLogic)

    if (unavailable) {
        return <LemonBanner type="info">AI credits aren't available for this organization yet.</LemonBanner>
    }

    return (
        <div className="@container/ai-credits flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <span className="flex items-center gap-1.5 text-secondary">
                    {spendSummary && (
                        <>
                            <IconCalendar />
                            {spendSummary.periodStart.format('MMM D')} –{' '}
                            {spendSummary.periodEnd.subtract(1, 'day').format('MMM D, YYYY')}
                        </>
                    )}
                </span>
                <LemonButton type="primary" onClick={openAddFundsModal} data-attr="ai-credits-add-funds">
                    Add funds
                </LemonButton>
            </div>
            <div className="grid gap-4 @min-[56rem]/ai-credits:grid-cols-3">
                <SpendThisPeriodTile />
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
