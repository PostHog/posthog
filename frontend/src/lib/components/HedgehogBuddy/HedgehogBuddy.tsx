import { useEffect, useRef, useState } from 'react'

import hhFall from 'public/hedgehog/sprites/fall.png'
import hhJump from 'public/hedgehog/sprites/jump.png'
import hhSign from 'public/hedgehog/sprites/sign.png'
import hhSpin from 'public/hedgehog/sprites/spin.png'
import hhWalk from 'public/hedgehog/sprites/walk.png'
import hhWave from 'public/hedgehog/sprites/wave.png'
import hhFallXmas from 'public/hedgehog/sprites/fall-xmas.png'
import hhJumpXmas from 'public/hedgehog/sprites/jump-xmas.png'
import hhSignXmas from 'public/hedgehog/sprites/sign-xmas.png'
import hhSpinXmas from 'public/hedgehog/sprites/spin-xmas.png'
import hhWalkXmas from 'public/hedgehog/sprites/walk-xmas.png'
import hhWaveXmas from 'public/hedgehog/sprites/wave-xmas.png'
import clsx from 'clsx'
import { capitalizeFirstLetter, range, sampleOne } from 'lib/utils'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useActions, useValues } from 'kea'
import { hedgehogbuddyLogic } from './hedgehogbuddyLogic'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

const size = 64
const imageWidth = 512
const xFrames = imageWidth / size
const boundaryPadding = 20
const fps = 20

const standardAnimations: {
    [key: string]: {
        frames: number
        img: string
        maxIteration?: number
        forceDirection?: 'left' | 'right'
        moveX?: number
        moveY?: number
        randomChance?: number
    }
} = {
    stop: {
        img: hhWave,
        frames: 1,
        maxIteration: 50,
        randomChance: 1,
    },
    fall: {
        img: hhFall,
        frames: 9,
        moveY: -10,
        forceDirection: 'left',
        randomChance: 0,
    },
    jump: {
        img: hhJump,
        frames: 10,
        maxIteration: 10,
        randomChance: 2,
    },
    sign: {
        img: hhSign,
        frames: 33,
        maxIteration: 1,
        forceDirection: 'right',
        randomChance: 1,
    },
    spin: {
        img: hhSpin,
        frames: 9,
        maxIteration: 3,
        randomChance: 2,
    },
    walk: {
        img: hhWalk,
        frames: 11,
        moveX: 1,
        moveY: 0,
        maxIteration: 20,
        randomChance: 10,
    },
    wave: {
        img: hhWave,
        frames: 27,
        maxIteration: 1,
        randomChance: 2,
    },
}

// Copy-paste but its only for xmas sooo...
const xmasAnimations: {
    [key: string]: {
        frames: number
        img: string
        maxIteration?: number
        forceDirection?: 'left' | 'right'
        moveX?: number
        moveY?: number
        randomChance?: number
    }
} = {
    stop: {
        img: hhWaveXmas,
        frames: 1,
        maxIteration: 50,
        randomChance: 1,
    },
    fall: {
        img: hhFallXmas,
        frames: 9,
        moveY: -10,
        forceDirection: 'left',
        randomChance: 0,
    },
    jump: {
        img: hhJumpXmas,
        frames: 10,
        maxIteration: 10,
        randomChance: 2,
    },
    sign: {
        img: hhSignXmas,
        frames: 33,
        maxIteration: 1,
        forceDirection: 'right',
        randomChance: 1,
    },
    spin: {
        img: hhSpinXmas,
        frames: 9,
        maxIteration: 3,
        randomChance: 2,
    },
    walk: {
        img: hhWalkXmas,
        frames: 11,
        moveX: 1,
        moveY: 0,
        maxIteration: 20,
        randomChance: 10,
    },
    wave: {
        img: hhWaveXmas,
        frames: 27,
        maxIteration: 1,
        randomChance: 2,
    },
}

const randomChoiceList: string[] = Object.keys(standardAnimations).reduce((acc: string[], key: string) => {
    return [...acc, ...range(standardAnimations[key].randomChance || 0).map(() => key)]
}, [])

export function HedgehogBuddy({ onClose }: { onClose: () => void }): JSX.Element {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const [_, setLoopTrigger] = useState(0)
    const iterationCount = useRef(0)
    const frameRef = useRef(0)
    const directionRef = useRef('right')
    const startX = Math.min(Math.max(0, Math.floor(Math.random() * window.innerWidth)), window.innerWidth - size)
    const position = useRef([startX, 200])
    const [isDragging, setIsDragging] = useState(false)
    const [popoverVisible, setPopoverVisible] = useState(false)

    const [animationName, setAnimationName] = useState('fall')

    const { featureFlags } = useValues(featureFlagLogic)
    const animations = featureFlags[FEATURE_FLAGS.YULE_HOG] ? xmasAnimations : standardAnimations
    const animation = animations[animationName]

    useEffect(() => {
        let timer: any = null
        let iterationsCountdown = animation.maxIteration
            ? Math.max(1, Math.floor(Math.random() * animation.maxIteration))
            : null

        const loop = (): void => {
            if (frameRef.current + 1 >= animation.frames && iterationsCountdown !== null) {
                iterationsCountdown -= 1
            }
            frameRef.current = frameRef.current + 1 >= animation.frames ? 0 : frameRef.current + 1
            setLoopTrigger(frameRef.current)
            timer = setTimeout(loop, 1000 / fps)

            const moveX = (animation.moveX || 0) * (directionRef.current === 'right' ? 1 : -1)
            const moveY = animation.moveY || 0

            if (isDragging) {
                return
            }

            position.current = [position.current[0] + moveX, position.current[1] + moveY]

            if (
                iterationsCountdown === 0 ||
                position.current[0] < boundaryPadding ||
                position.current[0] + size > window.innerWidth - boundaryPadding ||
                position.current[1] < 0 ||
                position.current[1] + size > window.innerHeight
            ) {
                position.current = [
                    Math.min(
                        Math.max(boundaryPadding, position.current[0]),
                        window.innerWidth - size - boundaryPadding
                    ),
                    Math.min(Math.max(0, position.current[1]), window.innerHeight - size),
                ]
                if (animationName === 'stop') {
                    const newAnimationName = sampleOne(randomChoiceList)
                    directionRef.current = animations[newAnimationName].forceDirection || sampleOne(['left', 'right'])

                    setAnimationName(newAnimationName)
                } else {
                    setAnimationName('stop')
                }
            }
        }

        loop()
        return () => {
            iterationCount.current = 0
            clearTimeout(timer)
        }
    }, [animation, isDragging])

    useEffect(() => {
        if (isDragging) {
            document.body.classList.add('select-none')
        } else {
            document.body.classList.remove('select-none')
        }

        return () => document.body.classList.remove('select-none')
    }, [isDragging])

    const onClick = (): void => {
        !isDragging && setPopoverVisible(!popoverVisible)
    }
    const disappear = (): void => {
        setPopoverVisible(false)
        setAnimationName('wave')
        setTimeout(() => onClose(), (animations.wave.frames * 1000) / fps)
    }

    return (
        <Popover
            onClickOutside={() => {
                setPopoverVisible(false)
                setAnimationName('fall')
            }}
            visible={popoverVisible}
            overlay={
                <div className="p-2">
                    <h3>Hello!</h3>
                    <p>
                        Don't mind me. I'm just here to keep you company.
                        <br />
                        You can move me around by clicking and dragging.
                    </p>
                    <div className="flex gap-2 my-2">
                        {['jump', 'sign', 'spin', 'wave'].map((x) => (
                            <LemonButton key={x} type="secondary" size="small" onClick={() => setAnimationName(x)}>
                                {capitalizeFirstLetter(x)}
                            </LemonButton>
                        ))}
                    </div>
                    <LemonDivider />
                    <div className="flex justify-end gap-2">
                        <LemonButton type="secondary" status="danger" onClick={() => disappear()}>
                            Good bye!
                        </LemonButton>
                        <LemonButton type="secondary" onClick={() => setPopoverVisible(false)}>
                            Carry on!
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div
                className={clsx('Hedgehog', {})}
                onMouseDown={() => {
                    let moved = false
                    const onMouseMove = (e: any): void => {
                        moved = true
                        setIsDragging(true)
                        setAnimationName('fall')
                        position.current = [e.clientX - size / 2, window.innerHeight - e.clientY - size / 2]
                    }

                    const onWindowUp = (): void => {
                        if (!moved) {
                            onClick()
                        }
                        setIsDragging(false)
                        setAnimationName('fall')
                        window.removeEventListener('mouseup', onWindowUp)
                        window.removeEventListener('mousemove', onMouseMove)
                    }
                    window.addEventListener('mousemove', onMouseMove)
                    window.addEventListener('mouseup', onWindowUp)
                }}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    position: 'fixed',
                    left: position.current[0],
                    bottom: position.current[1],
                    transition: !isDragging ? `all ${1000 / fps}ms` : undefined,
                    transform: `scaleX(${directionRef.current === 'right' ? 1 : -1})`,
                    cursor: 'pointer',
                    zIndex: 1001,
                }}
            >
                <div
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        imageRendering: 'pixelated',
                        width: size,
                        height: size,
                        backgroundImage: `url(${animation.img})`,
                        backgroundPosition: `-${(frameRef.current % xFrames) * size}px -${
                            Math.floor(frameRef.current / xFrames) * size
                        }px`,
                    }}
                />

                {/* We need to preload the images to avoid flashing on the first animation
                    The images are small and this is the best way I could find...  */}
                {Object.keys(animations).map((x) => (
                    <div
                        key={x}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            position: 'absolute',
                            width: 1, // This needs to be 1 as browsers are clever enough to realise the image isn't visible...
                            height: 1,
                            backgroundImage: `url(${animations[x].img})`,
                        }}
                    />
                ))}
            </div>
        </Popover>
    )
}

export function HedgehogBuddyWithLogic(): JSX.Element {
    const { hedgehogModeEnabled } = useValues(hedgehogbuddyLogic)
    const { setHedgehogModeEnabled } = useActions(hedgehogbuddyLogic)

    return hedgehogModeEnabled ? <HedgehogBuddy onClose={() => setHedgehogModeEnabled(false)} /> : <></>
}
