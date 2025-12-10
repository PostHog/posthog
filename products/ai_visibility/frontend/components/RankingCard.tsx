export function RankingCard({
    rank,
    brandName,
    topCompetitors,
}: {
    rank: number
    brandName: string
    topCompetitors: { name: string; visibility: number; logo_url: string }[]
}): JSX.Element {
    return (
        <div className="relative overflow-hidden rounded-lg bg-gradient-to-r from-[#1d4ed8] to-[#7c3aed] p-6 text-white">
            <div className="absolute right-0 top-0 h-full w-1/3 bg-gradient-to-l from-black/20 to-transparent" />
            <div className="relative z-10">
                <div className="flex items-baseline gap-1 mb-2">
                    <span className="text-5xl font-bold">#{rank}</span>
                    <span className="text-lg opacity-80">Most mentioned in your generated prompts</span>
                </div>
                <p className="text-sm opacity-80 mb-4">Login to PostHog to customize your prompts</p>
                <h3 className="text-xl font-semibold mb-3 text-white">Congratulations 🎉</h3>
                <div className="bg-black/30 rounded-lg p-4">
                    <div className="flex justify-between text-sm mb-2 opacity-80">
                        <span>Brand</span>
                        <span>% of AI responses that mention the brand</span>
                    </div>
                    {topCompetitors.slice(0, 3).map((comp, i) => (
                        <div key={comp.name} className="flex items-center justify-between py-2">
                            <div className="flex items-center gap-2">
                                <span className="text-lg">{i === 0 ? '🥇' : i === 1 ? '🥈' : '🥉'}</span>
                                <img src={comp.logo_url} alt="" className="w-5 h-5 rounded" />
                                <span className={comp.name === brandName ? 'font-bold' : ''}>{comp.name}</span>
                            </div>
                            <div className="flex items-center gap-3">
                                <div className="w-48 h-2 bg-white/20 rounded-full overflow-hidden">
                                    <div
                                        className="h-full bg-white/80 rounded-full"
                                        style={{ width: `${comp.visibility}%` }}
                                    />
                                </div>
                                <span className="w-12 text-right">{comp.visibility.toFixed(1)}%</span>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}
