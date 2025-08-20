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
            <div className="text-center mb-1">
                <h2 className="text-xl @md/max-welcome:text-2xl font-bold mb-2 text-balance">{headline}</h2>
                <div className="text-sm text-secondary text-pretty">{description}</div>
            </div>
        </>
    )
}
