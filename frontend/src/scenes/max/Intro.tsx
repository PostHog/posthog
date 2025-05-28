import { offset } from '@floating-ui/react'
import { IconDashboard, IconGraph, IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { hedgehogBuddyLogic } from 'lib/components/HedgehogBuddy/hedgehogBuddyLogic'
import { useState } from 'react'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { maxContextLogic } from '~/lib/ai/maxContextLogic'

import { maxLogic } from './maxLogic'

export function Intro(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { headline, description } = useValues(maxLogic)
    const { contextSummary } = useValues(maxContextLogic)

    const [hedgehogDirection, setHedgehogDirection] = useState<'left' | 'right'>('right')

    const getIconForType = (iconType: 'dashboard' | 'insights'): JSX.Element | null => {
        switch (iconType) {
            case 'dashboard':
                return <IconDashboard className="w-4 h-4" />
            case 'insights':
                return <IconGraph className="w-4 h-4" />
        }
        return null
    }

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
                <div className="text-sm text-secondary text-pretty">
                    {description}
                    {contextSummary && (
                        <Tooltip
                            title={
                                <div className="space-y-2">
                                    <div className="font-medium">Max has context about:</div>
                                    <ul className="space-y-1">
                                        {contextSummary.items.map((item, index) => (
                                            <li key={index} className="text-sm flex items-center gap-2">
                                                {getIconForType(item.icon)}
                                                {item.text}
                                            </li>
                                        ))}
                                    </ul>
                                    <div className="text-xs text-muted-foreground mt-2 pt-2 border-t">
                                        Max can answer questions about this data.
                                    </div>
                                </div>
                            }
                        >
                            <IconInfo className="ml-1 w-4 h-4 inline text-muted-foreground" />
                        </Tooltip>
                    )}
                </div>
            </div>
        </>
    )
}
