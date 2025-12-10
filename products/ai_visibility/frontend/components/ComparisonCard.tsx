import { CompetitorComparison } from '../types'

export function ComparisonCard({
    comparison,
    brandName,
}: {
    comparison: CompetitorComparison
    brandName: string
}): JSX.Element {
    const theyLeadPercentage = 100 - comparison.youLeadPercentage

    return (
        <div className="border rounded-lg p-5 bg-bg-light">
            <div className="flex items-center justify-between mb-4">
                <span className="font-semibold text-[#3b82f6]">{brandName}</span>
                <span className="text-xs text-muted">vs</span>
                <span className="font-semibold">{comparison.competitor}</span>
            </div>

            <div className="flex items-center justify-between mb-2">
                <p className="text-sm text-muted">
                    {brandName} appears higher for <span className="font-bold">{comparison.youLeadPercentage}%</span> of
                    shared prompts
                </p>
                <span className="text-sm text-muted">{comparison.sharedPrompts} shared prompts</span>
            </div>

            {/* Two-color progress bar */}
            <div className="flex h-3 rounded-full overflow-hidden mb-6">
                <div className="bg-[#3b82f6]" style={{ width: `${comparison.youLeadPercentage}%` }} />
                <div className="bg-[#eab308]" style={{ width: `${theyLeadPercentage}%` }} />
            </div>

            <div className="grid grid-cols-2 gap-6">
                <div>
                    <div className="flex items-center gap-2 mb-3">
                        <div className="w-3 h-3 rounded-full bg-[#3b82f6]" />
                        <span className="font-semibold text-sm">{brandName} leads in:</span>
                    </div>
                    <div className="space-y-2">
                        {comparison.youLeadsIn.map((item) => (
                            <div key={item.topic} className="flex justify-between text-sm">
                                <span className="text-muted">{item.topic}</span>
                                <span className="font-semibold">{item.percentage}%</span>
                            </div>
                        ))}
                        {comparison.youLeadsIn.length === 0 && <span className="text-sm text-muted">None</span>}
                    </div>
                </div>
                <div>
                    <div className="flex items-center gap-2 mb-3">
                        <div className="w-3 h-3 rounded-full bg-[#eab308]" />
                        <span className="font-semibold text-sm">{comparison.competitor} leads in:</span>
                    </div>
                    <div className="space-y-2">
                        {comparison.theyLeadIn.map((item) => (
                            <div key={item.topic} className="flex justify-between text-sm">
                                <span className="text-muted">{item.topic}</span>
                                <span className="font-semibold">{item.percentage}%</span>
                            </div>
                        ))}
                        {comparison.theyLeadIn.length === 0 && <span className="text-sm text-muted">None</span>}
                    </div>
                </div>
            </div>
        </div>
    )
}
