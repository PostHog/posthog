import React, { useEffect, useRef, useState } from 'react'

import hhFall from 'public/hedgehog/sprites/fall.png'
import hhJump from 'public/hedgehog/sprites/jump.png'
import hhSign from 'public/hedgehog/sprites/sign.png'
import hhSpin from 'public/hedgehog/sprites/spin.png'
import hhWalk from 'public/hedgehog/sprites/walk.png'
import hhWave from 'public/hedgehog/sprites/wave.png'
import clsx from 'clsx'
import { capitalizeFirstLetter, range, sampleOne } from 'lib/utils'
import { Popup } from '../Popup/Popup'
import { LemonButton } from '../LemonButton'
import { useActions, useValues } from 'kea'
import { hedgehogLogic } from './hedgehogLogic'
import { LemonDivider } from '../LemonDivider'

const s = 64
const w = 512
const xFrames = w / s
const fps = 20

const animations: {
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
        maxIteration: 10,
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

const randomChoiceList: string[] = Object.keys(animations).reduce((acc: string[], key: string) => {
    return [...acc, ...range(animations[key].randomChance || 0).map(() => key)]
}, [])

const startX = Math.min(Math.max(0, Math.floor(Math.random() * window.innerWidth)), window.innerWidth - s)
const startY = window.innerHeight - s * 2

export function Hedgehog({ onClose }: { onClose: () => void }): JSX.Element {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const [_, setLoopTrigger] = useState(0)
    const iterationCount = useRef(0)
    const frameRef = useRef(0)
    const directionRef = useRef('right')
    const position = useRef([startX, startY])
    const [isDragging, setIsDragging] = useState(false)
    const [popupVisible, setPopupVisible] = useState(false)

    const [animationName, setAnimationName] = useState('fall')
    const animation = animations[animationName]

    useEffect(() => {
        let timer: any = null
        let iterationsCountdown = animation.maxIteration
            ? Math.max(1, Math.floor(Math.random() * animation.maxIteration))
            : null

        console.log(
            `🦔 Hedgehog!! ${animationName} for ${
                iterationsCountdown ? iterationsCountdown * fps * animation.frames : 'lots of '
            }ms to the ${directionRef.current}`,
            animation,
            animations
        )

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
                position.current[0] < 0 ||
                position.current[0] + s > window.innerWidth ||
                position.current[1] < 0 ||
                position.current[1] + s > window.innerHeight
            ) {
                position.current = [
                    Math.min(Math.max(0, position.current[0]), window.innerWidth - s),
                    Math.min(Math.max(0, position.current[1]), window.innerHeight - s),
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

    const onClick = (): void => {
        !isDragging && setPopupVisible(!popupVisible)
    }
    const disappear = (): void => {
        setPopupVisible(false)
        setAnimationName('wave')
        setTimeout(() => onClose(), (animations.wave.frames * 1000) / fps)
    }

    return (
        <Popup
            onClickOutside={() => {
                setPopupVisible(false)
                setAnimationName('fall')
            }}
            visible={popupVisible}
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
                        <LemonButton type="secondary" onClick={() => setPopupVisible(false)}>
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
                        position.current = [e.clientX - s / 2, window.innerHeight - e.clientY - s / 2]
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
                        width: s,
                        height: s,
                        backgroundImage: `url(${animation.img})`,
                        backgroundPosition: `-${(frameRef.current % xFrames) * s}px -${
                            Math.floor(frameRef.current / xFrames) * s
                        }px`,
                    }}
                />
            </div>
        </Popup>
    )
}

export function HedgehogWithLogic(): JSX.Element {
    const { hedgehogModeEnabled } = useValues(hedgehogLogic)
    const { setHedgehogModeEnabled } = useActions(hedgehogLogic)

    return hedgehogModeEnabled ? <Hedgehog onClose={() => setHedgehogModeEnabled(false)} /> : <></>
}
