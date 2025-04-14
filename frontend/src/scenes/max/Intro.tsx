import { offset } from '@floating-ui/react'
import { useValues } from 'kea'
import { HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { hedgehogBuddyLogic } from 'lib/components/HedgehogBuddy/hedgehogBuddyLogic'
import { uuid } from 'lib/utils'
import { useMemo, useState } from 'react'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { maxLogic } from './maxLogic'

const HEADLINES = [
    'How can I help you build?',
    'What are you curious about?',
    'How can I help you understand users?',
    'What do you want to know today?',
]

export function Intro(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { conversation } = useValues(maxLogic)

    const [hedgehogDirection, setHedgehogDirection] = useState<'left' | 'right'>('right')

    const headline = useMemo(() => {
        if (process.env.STORYBOOK) {
            return HEADLINES[0] // Preventing UI snapshots from being different every time
        }
        return HEADLINES[parseInt((conversation?.id || uuid()).split('-').at(-1) as string, 16) % HEADLINES.length]
    }, [conversation?.id])

    return (
        <>
            <div className="flex">
                <AIConsentPopoverWrapper
                    placement={`${hedgehogDirection}-end`}
                    fallbackPlacements={[`${hedgehogDirection === 'right' ? 'left' : 'right'}-end`]}
                    middleware={[offset(-12)]}
                    showArrow
                >
                    <HedgehogBuddy
                        static
                        hedgehogConfig={{
                            ...hedgehogConfig,
                            walking_enabled: false,
                            controls_enabled: false,
                        }}
                        onClick={(actor) => {
                            if (Math.random() < 0.01) {
                                actor.setOnFire()
                            } else {
                                actor.setRandomAnimation()
                            }
                        }}
                        onActorLoaded={(actor) =>
                            setTimeout(() => {
                                actor.setAnimation('wave')
                                // Make the hedeghog face left, which looks better in the side panel
                                actor.direction = 'left'
                            }, 100)
                        }
                        onPositionChange={(actor) => setHedgehogDirection(actor.direction)}
                    />
                </AIConsentPopoverWrapper>
            </div>
            <div className="text-center mb-1">
                <h2 className="text-xl @md/max-welcome:text-2xl font-bold mb-2 text-balance">{headline}</h2>
                <div className="text-sm text-secondary text-balance">
                    I'm Max, here to help you build a successful&nbsp;product. Ask&nbsp;me about your product and
                    your&nbsp;users.
                </div>
            </div>
        </>
    )
}
