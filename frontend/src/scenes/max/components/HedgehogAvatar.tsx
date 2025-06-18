import { IconSparkles } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { HedgehogActor, HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { useEffect, useRef } from 'react'
import { userLogic } from 'scenes/userLogic'

interface HedgehogAvatarProps {
    onExpand: () => void
    waveInterval?: number
    isExpanded: boolean
}

export function HedgehogAvatar({ onExpand, waveInterval = 5000, isExpanded }: HedgehogAvatarProps): JSX.Element {
    const { user } = useValues(userLogic)
    const hedgehogActorRef = useRef<HedgehogActor | null>(null)

    // Trigger wave animation periodically when collapsed
    useEffect(() => {
        let interval: ReturnType<typeof setInterval> | null = null

        if (!isExpanded && hedgehogActorRef.current) {
            interval = setInterval(() => {
                hedgehogActorRef.current?.setAnimation('wave')
            }, waveInterval)
        }

        return () => {
            if (interval) {
                clearInterval(interval)
            }
        }
    }, [isExpanded, waveInterval])

    return (
        <div className="relative flex items-center justify-end mb-2 mr-4">
            <Tooltip
                title={
                    <>
                        <IconSparkles className="mr-1.5" />
                        Max AI - Create insights, talk to your data, and more
                    </>
                }
                placement="top-start"
                delayMs={0}
            >
                <div
                    className="size-10 rounded-full overflow-hidden border border-border-primary shadow-lg hover:shadow-xl transition-all duration-200 cursor-pointer -scale-x-100 hover:scale-y-110 hover:-scale-x-110 flex items-center justify-center bg-bg-light"
                    onClick={onExpand}
                >
                    <HedgehogBuddy
                        static
                        hedgehogConfig={{
                            controls_enabled: false,
                            walking_enabled: false,
                            color: null,
                            enabled: true,
                            accessories: [],
                            interactions_enabled: false,
                            party_mode_enabled: false,
                            use_as_profile: true,
                            skin: 'default',
                            ...user?.hedgehog_config,
                        }}
                        onActorLoaded={(actor) => {
                            hedgehogActorRef.current = actor
                            // Start with a wave
                            actor.setAnimation('wave')
                        }}
                    />
                </div>
            </Tooltip>
        </div>
    )
}
