import { useMemo } from 'react'

import { IconShare } from '@posthog/icons'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import businessHog from 'public/hedgehog/business-hog.png'

const TAUNT_MESSAGES = [
    'Your friends and competitors are jealous of you!',
    'Your competitors are crying into their keyboards right now.',
    "Someone's SEO team is getting fired today. Not yours though.",
    'The AI overlords have spoken. They like you better.',
    "Your competitors' marketing budget just felt a disturbance in the force.",
    "Plot twist: you're the main character.",
]

const SHARE_TEXTS = [
    'Let everyone know!',
    'Rub it in their faces',
    'Time to gloat',
    'Make them jealous',
    'Flex on the haters',
    'Send to your competitors',
]

export function RankingCard({
    rank,
    brandName,
    topCompetitors,
}: {
    rank: number
    brandName: string
    topCompetitors: { name: string; visibility: number; domain?: string }[]
}): JSX.Element {
    const { tauntMessage, shareText } = useMemo(
        () => ({
            tauntMessage: TAUNT_MESSAGES[Math.floor(Math.random() * TAUNT_MESSAGES.length)],
            shareText: SHARE_TEXTS[Math.floor(Math.random() * SHARE_TEXTS.length)],
        }),
        []
    )

    return (
        <div className="relative overflow-hidden rounded-lg bg-[#f54e00] p-6 text-white border-l-4 border-l-[#1d1f27]">
            {/* Business hedgehog pointing at results */}
            <img src={businessHog} alt="" className="absolute -bottom-10 -right-16 w-64 h-64 object-contain z-20" />
            <div className="relative z-10">
                <div className="flex items-baseline gap-1 mb-2">
                    <span className="text-5xl font-bold mr-2">#{rank}</span>
                    <span className="text-lg opacity-80">Most mentioned in your generated prompts</span>
                </div>
                <h3 className="text-xl font-semibold mb-3 text-white">You're Awesome! 🎉</h3>
                <div className="bg-black/30 rounded-lg p-4 mt-">
                    <div className="flex justify-between text-sm mb-2 opacity-80">
                        <span>Brand</span>
                        <span>% of AI responses that mention the brand</span>
                    </div>
                    {topCompetitors.slice(0, 3).map((comp, i) => {
                        const faviconDomain = comp.domain || comp.name
                        return (
                            <div key={comp.name} className="flex items-center justify-between py-2">
                                <div className="flex items-center gap-2">
                                    <span className="text-lg">{i === 0 ? '🥇' : i === 1 ? '🥈' : '🥉'}</span>
                                    <img
                                        src={`https://www.google.com/s2/favicons?domain=${faviconDomain}&sz=32`}
                                        alt=""
                                        className="w-5 h-5 rounded"
                                    />
                                    <span className={comp.name === brandName ? 'font-bold' : ''}>{comp.name}</span>
                                </div>
                                <div className="flex items-center gap-3">
                                    <div className="w-48 h-2 bg-white/20 rounded-full overflow-hidden">
                                        <div
                                            className="h-full bg-white rounded-full"
                                            style={{ width: `${comp.visibility}%` }}
                                        />
                                    </div>
                                    <span className="w-12 text-right">{comp.visibility.toFixed(1)}%</span>
                                </div>
                            </div>
                        )
                    })}
                </div>
                <div className="mt-4 max-w-md">
                    <span className="text-sm opacity-80">{tauntMessage}</span>
                    <button
                        type="button"
                        onClick={() => copyToClipboard(window.location.href, 'link')}
                        className="mt-4 flex items-center gap-2 rounded-md bg-white/20 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-white/30"
                    >
                        <IconShare className="h-4 w-4" />
                        {shareText}
                    </button>
                </div>
            </div>
        </div>
    )
}
