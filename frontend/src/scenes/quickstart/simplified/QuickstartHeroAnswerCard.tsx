import { useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { quickstartLogic } from '../quickstartLogic'
import { captureQuickstartAction } from '../shared/captureQuickstartAction'

// The test2 hero: one computed answer from the org's own data, shown above the cards so
// undecided users fall into doing something instead of scanning a menu.
export function QuickstartHeroAnswerCard(): JSX.Element | null {
    const { heroAnswer } = useValues(quickstartLogic)

    if (!heroAnswer) {
        return null
    }
    return (
        <section>
            <LemonCard hoverEffect={false} className="flex flex-wrap items-center justify-between gap-4 p-6">
                <div className="min-w-0">
                    <h2 className="text-xl font-semibold mb-0">{heroAnswer.headline}</h2>
                    <p className="text-secondary mb-0 mt-1">{heroAnswer.detail}</p>
                </div>
                <LemonButton
                    type="primary"
                    to={heroAnswer.url}
                    icon={<IconArrowRight />}
                    onClick={() =>
                        captureQuickstartAction('open_hero_answer', heroAnswer.productKey, {
                            hero_headline: heroAnswer.headline,
                        })
                    }
                    data-attr="quickstart-hero-answer-cta"
                >
                    {heroAnswer.ctaLabel}
                </LemonButton>
            </LemonCard>
        </section>
    )
}
