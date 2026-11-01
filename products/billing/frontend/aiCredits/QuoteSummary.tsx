import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { humanFriendlyCurrency } from 'lib/utils/numbers'

import { aiCreditsLogic } from './aiCreditsLogic'

export function QuoteSummary(): JSX.Element {
    const { quote, quoteLoading, quoteError } = useValues(aiCreditsLogic)

    return (
        // The quote spans the modal's width, so it pulls out past the content padding.
        <div className="-mx-4 flex flex-col gap-2.5 border-y bg-fill-secondary px-4 py-4">
            {quoteError ? (
                <span className="text-danger">{quoteError}</span>
            ) : quoteLoading || !quote ? (
                <LemonSkeleton repeat={3} />
            ) : (
                <>
                    <div className="flex justify-between">
                        <span className="text-secondary">Purchase</span>
                        <span>{humanFriendlyCurrency(quote.amount_usd)}</span>
                    </div>
                    <div className="flex justify-between">
                        <span className="text-secondary">Tax</span>
                        <span>{humanFriendlyCurrency(quote.tax_usd)}</span>
                    </div>
                    <div className="flex justify-between border-t pt-2.5 text-base font-semibold">
                        <span>Total due today</span>
                        <span className="font-bold">{humanFriendlyCurrency(quote.total_usd)}</span>
                    </div>
                </>
            )}
        </div>
    )
}
