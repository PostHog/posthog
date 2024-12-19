import { offset } from '@floating-ui/react'
import { IconLock, IconUnlock } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { hedgehogBuddyLogic } from 'lib/components/HedgehogBuddy/hedgehogBuddyLogic'
import { uuid } from 'lib/utils'
import { useMemo, useState } from 'react'

import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'

const HEADLINES = [
    'How can I help you build?',
    'What are you curious about?',
    'How can I help you understand users?',
    'What do you want to know today?',
]

export function Intro(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { acceptDataProcessing } = useActions(maxGlobalLogic)
    const { dataProcessingApprovalDisabledReason, dataProcessingAccepted } = useValues(maxGlobalLogic)
    const { conversation } = useValues(maxLogic)

    const [hedgehogDirection, setHedgehogDirection] = useState<'left' | 'right'>('right')

    const headline = useMemo(() => {
        return HEADLINES[parseInt((conversation?.id || uuid()).split('-').at(-1) as string, 16) % HEADLINES.length]
    }, [conversation?.id])

    return (
        <>
            <div className="flex">
                <Popover
                    overlay={
                        <div className="m-1.5">
                            <p className="font-medium text-pretty mb-1.5">
                                Hi! I use OpenAI services to analyze your data,
                                <br />
                                so that you can focus on building. This <em>can</em> include
                                <br />
                                personal data of your users, if you're capturing it.
                                <br />
                                <em>Your data won't be used for training models.</em>
                            </p>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => acceptDataProcessing()}
                                sideIcon={dataProcessingApprovalDisabledReason ? <IconLock /> : <IconUnlock />}
                                disabledReason={dataProcessingApprovalDisabledReason}
                                tooltip="You are approving this as an organization admin"
                                tooltipPlacement="bottom"
                            >
                                I allow OpenAI-based analysis in this organization
                            </LemonButton>
                        </div>
                    }
                    placement={`${hedgehogDirection}-end`}
                    middleware={[offset(-12)]}
                    showArrow
                    visible={!dataProcessingAccepted}
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
                                // Always start out facing right so that the data processing popover is more readable
                                actor.direction = 'right'
                            }, 100)
                        }
                        onPositionChange={(actor) => setHedgehogDirection(actor.direction)}
                    />
                </Popover>
            </div>
            <div className="text-center mb-3">
                <h2 className="text-2xl font-bold mb-2 text-balance">{headline}</h2>
                <div className="text-muted text-balance">
                    I'm Max, here to help you build a succesful product. Ask me about your product and your users.
                </div>
            </div>
        </>
    )
}
