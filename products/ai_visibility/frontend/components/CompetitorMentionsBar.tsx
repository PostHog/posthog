import clsx from 'clsx'

export function CompetitorMentionsBar({
    brandName,
    visibilityScore,
    competitors,
    onViewAll,
}: {
    brandName: string
    visibilityScore: number
    competitors: { name: string; visibility: number; logo_url?: string }[]
    onViewAll?: () => void
}): JSX.Element {
    // Build full sorted list to get accurate rankings
    const brandLogoUrl = `https://www.google.com/s2/favicons?domain=${brandName}&sz=128`
    const fullList = [
        { name: brandName, visibility: visibilityScore, isOurBrand: true, logo_url: brandLogoUrl },
        ...competitors.map((c) => ({
            ...c,
            isOurBrand: false,
            logo_url:
                c.logo_url ||
                `https://www.google.com/s2/favicons?domain=${c.name.toLowerCase().replace(/\s+/g, '')}.com&sz=128`,
        })),
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
                <h3 className="text-sm font-semibold">Competitor mentions vs {brandName}</h3>
                {onViewAll && (
                    <button onClick={onViewAll} className="text-xs text-primary hover:underline cursor-pointer">
                        View all
                    </button>
                )}
            </div>
            <div className="space-y-3">
                {displayList.map((brand) => (
                    <div key={brand.name} className="flex items-center gap-3">
                        <span
                            className={clsx(
                                'w-6 text-sm text-muted text-right',
                                brand.isOurBrand && 'text-[#f97316] font-semibold'
                            )}
                        >
                            {brand.rank}
                        </span>
                        <img src={brand.logo_url} alt="" className="w-5 h-5 rounded" />
                        <span className={clsx('w-24 text-sm truncate', brand.isOurBrand && 'font-semibold')}>
                            {brand.name}
                        </span>
                        <div className="flex-1 h-4 bg-border rounded overflow-hidden">
                            <div
                                className={clsx('h-full rounded', brand.isOurBrand ? 'bg-[#f97316]' : 'bg-gray-400')}
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
                ))}
            </div>
        </div>
    )
}
