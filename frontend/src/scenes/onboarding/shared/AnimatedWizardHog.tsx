import type { AnimationItem, LottiePlayer } from 'lottie-web'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useInView } from 'react-intersection-observer'

import { cn } from 'lib/utils/css-classes'
import { inStorybookTestRunner } from 'lib/utils/dom'

import { WizardHog } from './wizardHog'

// Frames of wizardHogAnimation.json, drawn at 24fps. From CAST_START the hog raises its staff and sparkles; from
// IDLE_START it bobs and blinks until END, whose pose matches IDLE_START's so that stretch loops without a jump.
const CAST_START = 20
const IDLE_START = 96
const END = 240

type WizardHogAnimation = [player: LottiePlayer, data: unknown]

let loading: Promise<WizardHogAnimation> | null = null

function loadWizardHogAnimation(): Promise<WizardHogAnimation> {
    loading ??= Promise.all([import('lottie-web/build/player/lottie_light'), import('./wizardHogAnimation.json')]).then(
        ([player, data]): WizardHogAnimation => [player.default, data.default],
        (error) => {
            loading = null
            throw error
        }
    )
    return loading
}

export interface AnimatedWizardHogProps {
    className?: string
    speed?: number
    idle?: boolean
    /** The hog raises its staff and sparkles each time this changes. 0 never casts. */
    castKey?: number
}

export function AnimatedWizardHog({
    className,
    speed = 1,
    idle = true,
    castKey = 0,
}: AnimatedWizardHogProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { ref: inViewRef, inView } = useInView()
    const visible = useRef(inView)
    visible.current = inView
    const [seen, setSeen] = useState(inView)
    if (inView && !seen) {
        setSeen(true)
    }
    const setContainer = useCallback(
        (element: HTMLDivElement | null) => {
            containerRef.current = element
            inViewRef(element)
        },
        [inViewRef]
    )
    const [still] = useState(
        () => inStorybookTestRunner() || !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    )
    const [animation, setAnimation] = useState<AnimationItem | null>(null)
    const [failed, setFailed] = useState(false)
    const playedCastKey = useRef(0)
    const playing = useRef(false)

    useEffect(() => {
        if (still || !seen) {
            return
        }
        let cancelled = false
        let item: AnimationItem | null = null
        loadWizardHogAnimation().then(
            ([player, data]) => {
                if (cancelled || !containerRef.current) {
                    return
                }
                item = player.loadAnimation({
                    container: containerRef.current,
                    renderer: 'svg',
                    loop: false,
                    autoplay: false,
                    animationData: data,
                })
                item.addEventListener('complete', () => {
                    playing.current = false
                })
                setAnimation(item)
            },
            () => {
                if (!cancelled) {
                    setFailed(true)
                }
            }
        )
        return () => {
            cancelled = true
            item?.destroy()
        }
    }, [still, seen])

    useEffect(() => {
        animation?.setSpeed(speed)
    }, [animation, speed])

    useEffect(() => {
        if (!animation) {
            return
        }
        const cast = castKey !== playedCastKey.current
        playedCastKey.current = castKey
        animation.setLoop(idle)
        if (cast) {
            // With looping on, the player moves to the queued idle stretch after the cast and keeps repeating it.
            animation.playSegments(
                idle
                    ? [
                          [CAST_START, IDLE_START],
                          [IDLE_START, END],
                      ]
                    : [CAST_START, IDLE_START],
                true
            )
        } else if (idle) {
            animation.playSegments([IDLE_START, END], true)
        } else {
            animation.goToAndStop(IDLE_START, true)
        }
        playing.current = cast || idle
        if (!visible.current) {
            animation.pause()
        }
    }, [animation, castKey, idle])

    useEffect(() => {
        if (!animation) {
            return
        }
        if (!inView) {
            animation.pause()
        } else if (playing.current) {
            animation.play()
        }
    }, [animation, inView])

    if (still || failed) {
        return <WizardHog className={className} loading="eager" />
    }

    return (
        <div
            ref={setContainer}
            aria-hidden
            className={cn(
                // Icon slots such as the nav rail tile size every svg inside them, which would shrink the player's svg.
                'aspect-square transition-opacity duration-150 [&>svg]:!size-full',
                animation ? 'opacity-100' : 'opacity-0',
                className
            )}
        />
    )
}
