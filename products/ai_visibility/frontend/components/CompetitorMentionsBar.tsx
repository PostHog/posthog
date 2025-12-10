import clsx from 'clsx'

import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

export function CompetitorMentionsBar({
    brandName,
    brandDomain,
    visibilityScore,
    competitors,
    onViewAll,
}: {
    brandName: string
    brandDomain: string
    visibilityScore: number
    competitors: { name: string; visibility: number; domain?: string }[]
    onViewAll?: () => void
}): JSX.Element {
    // Build full sorted list to get accurate rankings
    const fullList = [
        { name: brandName, domain: brandDomain, visibility: visibilityScore, isOurBrand: true },
        ...competitors.map((c) => ({ ...c, isOurBrand: false })),
    ].sort((a, b) => b.visibility - a.visibility)

    // Add rank to each entry
    const rankedList = fullList.map((brand, index) => ({ ...brand, rank: index + 1 }))

    // Get top 9 competitors + our brand (with their true ranks)
    const ourBrand = rankedList.find((b) => b.isOurBrand)!
    const topCompetitors = rankedList.filter((b) => !b.isOurBrand).slice(0, 9)
    const displayList = [...topCompetitors, ourBrand].sort((a, b) => a.rank - b.rank)

    const maxVisibility = Math.max(...displayList.map((b) => b.visibility), 1)

    return (
        <div className="border rounded-lg p-4 bg-bg-light">
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold flex items-center gap-1">
                    Competitor mentions vs {brandName}
                    <Tooltip title="Compares how often your brand is mentioned vs competitors across all AI responses. Higher percentage = more visibility.">
                        <IconInfo className="w-4 h-4 text-muted" />
                    </Tooltip>
                </h3>
                {onViewAll && (
                    <button onClick={onViewAll} className="text-xs text-primary hover:underline cursor-pointer">
                        View all
                    </button>
                )}
            </div>
            <div className="space-y-3">
                {displayList.map((brand) => {
                    const faviconDomain = brand.domain || brand.name
                    return (
                        <div key={brand.name} className="flex items-center gap-3">
                            <span
                                className={clsx(
                                    'w-6 text-sm text-muted text-right',
                                    brand.isOurBrand && 'text-[#f97316] font-semibold'
                                )}
                            >
                                {brand.rank}
                            </span>
                            <div className={clsx('w-32 flex items-center gap-2', brand.isOurBrand && 'font-semibold')}>
                                <img
                                    src={`https://www.google.com/s2/favicons?domain=${faviconDomain}&sz=32`}
                                    alt=""
                                    className="w-4 h-4 rounded"
                                />
                                <span className="text-sm truncate">{brand.name}</span>
                            </div>
                            <div className="flex-1 h-4 bg-border rounded overflow-hidden">
                                <div
                                    className={clsx(
                                        'h-full rounded',
                                        brand.isOurBrand ? 'bg-[#f97316]' : 'bg-gray-400'
                                    )}
                                    style={{ width: `${(brand.visibility / maxVisibility) * 100}%` }}
                                />
                            </div>
                            <span
                                className={clsx(
                                    'w-10 text-sm text-right',
                                    brand.isOurBrand ? 'text-[#f97316] font-semibold' : ''
                                )}
                            >
                                {brand.visibility}%
                            </span>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
