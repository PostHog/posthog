import { LemonButton, Popover } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { hedgehogBuddyLogic } from 'lib/components/HedgehogBuddy/hedgehogBuddyLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

export const AiConsentPopover = (): JSX.Element => {
    const { acceptDataProcessing } = useActions(maxGlobalLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)

    if (dataProcessingAccepted) {
        return <></>
    }

    return (
        <>
            <div className="flex justify-center">
                <Popover
                    overlay={
                        <div className="m-1.5 max-w-80">
                            <p className="font-medium text-pretty mb-1.5">
                                Hi! This feature uses OpenAI to analyze your data, helping you gain insights faster. If
                                your data includes personal information, it may be processed.
                                <br />
                                Your data won't be used for AI training.
                            </p>
                            <LemonButton type="secondary" size="small" onClick={() => acceptDataProcessing()}>
                                Got it, I accept OpenAI processing my data
                            </LemonButton>
                        </div>
                    }
                    placement="right-end"
                    showArrow
                    visible={true}
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
                    />
                </Popover>
            </div>
        </>
    )
}
