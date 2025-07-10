import { useValues } from 'kea'

import { HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { hedgehogBuddyLogic } from 'lib/components/HedgehogBuddy/hedgehogBuddyLogic'

import { maxLogic } from './maxLogic'

export function Intro(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { headline, description } = useValues(maxLogic)

    return (
        <>
            <div className="flex">
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
                            actor.setRandomAnimation(['stop'])
                        }
                    }}
                    onActorLoaded={(actor) =>
                        setTimeout(() => {
                            actor.setAnimation('wave')
                            // Make the hedeghog face left, which looks better in the side panel
                            actor.direction = 'left'
                        }, 100)
                    }
                />
            </div>
            <div className="mb-1 text-center">
                <h2 className="@md/max-welcome:text-2xl mb-2 text-balance text-xl font-bold">{headline}</h2>
                <div className="text-secondary text-pretty text-sm">{description}</div>
            </div>
        </>
    )
}
