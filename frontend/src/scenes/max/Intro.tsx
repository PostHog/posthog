import { useValues } from 'kea'
import { HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { hedgehogBuddyLogic } from 'lib/components/HedgehogBuddy/hedgehogBuddyLogic'
import { useMemo } from 'react'

const HEADLINES = [
    'How can I help you build?',
    'What are you curious about?',
    'How can I help you understand users?',
    'What do you want to know today?',
]

export function Intro(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)

    const headline = useMemo(() => {
        return HEADLINES[Math.floor(Math.random() * HEADLINES.length)]
    }, [])

    return (
        <>
            {' '}
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
                            actor.setRandomAnimation()
                        }
                    }}
                    onActorLoaded={(actor) => setTimeout(() => actor.setAnimation('wave'), 100)}
                />
            </div>
            <div className="text-center mb-2">
                <h2 className="text-2xl font-bold mb-2 text-balance">{headline}</h2>
                <span className="text-muted">
                    I'm Max, here to help you build a succesful product. Ask me about your product and your users.
                </span>
            </div>{' '}
        </>
    )
}
