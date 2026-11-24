import { humanFriendlyCurrency } from 'lib/utils/numbers'

function weeklyCost(usd: number | null): string {
    if (usd === null) {
        return 'Billed per run'
    }
    return usd < 0.01 ? 'Under $0.01/week' : `${humanFriendlyCurrency(usd)}/week`
}

/** Only LLM judges call the project's AI provider; code checks and sentiment run without it. */
export function EvaluationSuggestionCost({
    usesProvider,
    weeklyCostUsd,
}: {
    usesProvider: boolean
    weeklyCostUsd: number | null
}): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5 pt-2 border-t border-primary text-xs">
            <div className="flex flex-wrap justify-between gap-x-2">
                <span className="text-secondary">
                    {usesProvider ? 'Estimated AI provider cost' : 'AI provider cost'}
                </span>
                <span className="font-semibold">{usesProvider ? weeklyCost(weeklyCostUsd) : 'None'}</span>
            </div>
            {usesProvider && <span className="text-secondary">Uses your API key</span>}
        </div>
    )
}
