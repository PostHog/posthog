import { useEffect, useRef, useState } from 'react'

import clsx from 'clsx'
import { capitalizeFirstLetter, range, sampleOne } from 'lib/utils'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useActions, useValues } from 'kea'
import { hedgehogbuddyLogic } from './hedgehogbuddyLogic'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { SPRITE_SHEET_WIDTH, SPRITE_SIZE, standardAnimations } from './sprites/sprites'

const xFrames = SPRITE_SHEET_WIDTH / SPRITE_SIZE
const boundaryPadding = 20
const FPS = 24
const GRAVITY_PIXELS = 10
const MAX_JUMP_COUNT = 2

const randomChoiceList: string[] = Object.keys(standardAnimations).reduce((acc: string[], key: string) => {
    return [...acc, ...range(standardAnimations[key].randomChance || 0).map(() => key)]
}, [])

class HedgehogActor {
    animations = standardAnimations
    iterationCount = 0
    frameRef = 0
    direction: 'left' | 'right' = 'right'
    startX = Math.min(Math.max(0, Math.floor(Math.random() * window.innerWidth)), window.innerWidth - SPRITE_SIZE)
    startY = Math.min(Math.max(0, Math.floor(Math.random() * window.innerHeight)), window.innerHeight - SPRITE_SIZE)
    x = this.startX
    y = this.startY
    isDragging = false
    yVelocity = -30
    xVelocity = 0
    onGround = false
    jumpCount = 0

    animationName: string = 'fall'
    animation = this.animations[this.animationName]
    animationFrame = 0
    animationIterations: number | null = null

    constructor() {
        this.setAnimation('fall')
    }

    setupKeyboardListeners(): () => void {
        const keyDownListener = (e: KeyboardEvent): void => {
            const key = e.key.toLowerCase()
            if ([' ', 'w', 'arrowup'].includes(key)) {
                this.jump()
            }

            if (['arrowdown', 's'].includes(key)) {
                if (this.animationName !== 'spin') {
                    this.setAnimation('spin')
                }
                this.animationIterations = null
            }

            if (['arrowleft', 'a', 'arrowright', 'd'].includes(key)) {
                if (this.animationName !== 'walk') {
                    this.setAnimation('walk')
                }

                this.direction = ['arrowleft', 'a'].includes(key) ? 'left' : 'right'
                this.xVelocity = this.direction === 'left' ? -5 : 5

                const moonwalk = e.shiftKey
                if (moonwalk) {
                    this.direction = this.direction === 'left' ? 'right' : 'left'
                    // Moonwalking is hard so he moves slightly slower of course
                    this.xVelocity *= 0.8
                }

                this.animationIterations = null
            }
        }

        const keyUpListener = (e: KeyboardEvent): void => {
            const key = e.key.toLowerCase()

            if (key === ' ') {
                this.jump()
            }

            if (['arrowdown', 's'].includes(key)) {
                this.setAnimation('stop')
                this.animationIterations = FPS * 2 // Wait 2 seconds before doing something else
            }

            if (['arrowleft', 'a', 'arrowright', 'd', 'arrowdown', 's'].includes(key)) {
                this.setAnimation('stop')
                this.animationIterations = FPS * 2 // Wait 2 seconds before doing something else
            }
        }

        window.addEventListener('keydown', keyDownListener)
        window.addEventListener('keyup', keyUpListener)

        return () => {
            window.removeEventListener('keydown', keyDownListener)
            window.removeEventListener('keyup', keyUpListener)
        }
    }

    setAnimation(animationName: string): void {
        this.animationName = animationName
        this.animation = this.animations[animationName]
        this.animationFrame = 0
        if (this.animationName !== 'stop') {
            this.direction = this.animation.forceDirection || sampleOne(['left', 'right'])
        }

        // Set a random number of iterations or infinite for certain situations
        this.animationIterations = this.animation.maxIteration
            ? Math.max(1, Math.floor(Math.random() * this.animation.maxIteration))
            : null

        if (animationName === 'walk') {
            this.xVelocity = this.direction === 'left' ? -1 : 1
        } else {
            this.xVelocity = 0
        }

        if (window.JS_POSTHOG_SELF_CAPTURE || (window as any).debugHedgehog) {
            const duration = this.animationIterations
                ? this.animationIterations * this.animation.frames * (1000 / FPS)
                : '∞'
            console.log(`Hedgehog: Will '${this.animationName}' for ${duration}ms`)
        }
    }

    setRandomAnimation(): void {
        if (this.animationName !== 'stop') {
            this.setAnimation('stop')
        } else {
            this.setAnimation(sampleOne(randomChoiceList))
        }
    }

    jump(): void {
        if (this.jumpCount > MAX_JUMP_COUNT) {
            return
        }
        this.jumpCount += 1
        this.yVelocity = -GRAVITY_PIXELS * 5
    }

    update(): void {
        this.applyGravity()

        // Ensure we are falling or not
        if (this.animationName === 'fall' && this.onGround) {
            this.setAnimation('stop')
        }

        this.animationFrame++

        if (this.animationFrame >= this.animation.frames) {
            // End of the animation
            if (this.animationIterations !== null) {
                this.animationIterations -= 1
            }

            if (this.animationIterations === 0) {
                this.animationIterations = null
                // End of the animation, set the next one
                this.setRandomAnimation()
            }

            this.animationFrame = 0
        }

        this.x = this.x + this.xVelocity

        if (this.x < boundaryPadding) {
            this.direction = 'right'
            this.x = boundaryPadding
            this.xVelocity = -this.xVelocity
        }

        if (this.x > window.innerWidth - SPRITE_SIZE - boundaryPadding) {
            this.direction = 'left'
            this.x = window.innerWidth - SPRITE_SIZE - boundaryPadding
            this.xVelocity = -this.xVelocity
        }
    }

    private applyGravity(): void {
        this.onGround = false
        if (this.isDragging) {
            return
        }

        this.yVelocity += GRAVITY_PIXELS
        this.y -= this.yVelocity

        if (this.y <= 0) {
            this.y = 0
            this.onGround = true
            this.jumpCount = 0

            // Apply bounce with friction
            this.yVelocity = -this.yVelocity * 0.4

            if (this.yVelocity > -GRAVITY_PIXELS) {
                // We are so close to the ground that we may as well be on it
                this.yVelocity = 0
            }
        }
    }

    render({ onClick }: { onClick: () => void }): JSX.Element {
        return (
            <div
                className={clsx('Hedgehog', {})}
                onMouseDown={() => {
                    let moved = false
                    const onMouseMove = (e: any): void => {
                        moved = true
                        this.isDragging = true
                        this.setAnimation('fall')
                        this.x = e.clientX - SPRITE_SIZE / 2
                        this.y = window.innerHeight - e.clientY - SPRITE_SIZE / 2
                    }

                    const onWindowUp = (): void => {
                        if (!moved) {
                            onClick()
                        }
                        this.isDragging = false
                        this.setAnimation('fall')
                        window.removeEventListener('mouseup', onWindowUp)
                        window.removeEventListener('mousemove', onMouseMove)
                    }
                    window.addEventListener('mousemove', onMouseMove)
                    window.addEventListener('mouseup', onWindowUp)
                }}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    position: 'fixed',
                    left: this.x,
                    bottom: this.y,
                    transition: !this.isDragging ? `all ${1000 / FPS}ms` : undefined,
                    transform: `scaleX(${this.direction === 'right' ? 1 : -1})`,
                    cursor: 'pointer',
                    zIndex: 1001,
                }}
            >
                <div
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        imageRendering: 'pixelated',
                        width: SPRITE_SIZE,
                        height: SPRITE_SIZE,
                        backgroundImage: `url(${this.animation.img})`,
                        backgroundPosition: `-${(this.animationFrame % xFrames) * SPRITE_SIZE}px -${
                            Math.floor(this.animationFrame / xFrames) * SPRITE_SIZE
                        }px`,
                    }}
                />

                {/* We need to preload the images to avoid flashing on the first animation
                    The images are small and this is the best way I could find...  */}
                {Object.keys(this.animations).map((x) => (
                    <div
                        key={x}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            position: 'absolute',
                            width: 1, // This needs to be 1 as browsers are clever enough to realise the image isn't visible...
                            height: 1,
                            backgroundImage: `url(${this.animations[x].img})`,
                        }}
                    />
                ))}
            </div>
        )
    }
}

export function HedgehogBuddy({ onClose }: { onClose: () => void }): JSX.Element {
    const actorRef = useRef<HedgehogActor>()

    if (!actorRef.current) {
        actorRef.current = new HedgehogActor()
    }

    const actor = actorRef.current

    useEffect(() => {
        return actor.setupKeyboardListeners()
    }, [])

    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const [_, setTimerLoop] = useState(0)

    const [popoverVisible, setPopoverVisible] = useState(false)

    useEffect(() => {
        let timer: any = null

        const loop = (): void => {
            actor.update()
            setTimerLoop((x) => x + 1)
            timer = setTimeout(loop, 1000 / FPS)
        }

        loop()
        return () => {
            clearTimeout(timer)
        }
    }, [])

    useEffect(() => {
        if (actor.isDragging) {
            document.body.classList.add('select-none')
        } else {
            document.body.classList.remove('select-none')
        }

        return () => document.body.classList.remove('select-none')
    }, [actor.isDragging])

    const onClick = (): void => {
        !actor.isDragging && setPopoverVisible(!popoverVisible)
    }
    const disappear = (): void => {
        setPopoverVisible(false)
        actor.setAnimation('wave')
        setTimeout(() => onClose(), (actor.animations.wave.frames * 1000) / FPS)
    }

    return (
        <Popover
            onClickOutside={() => {
                setPopoverVisible(false)
                // setAnimationName('fall')
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
                        {['jump', 'sign', 'spin', 'wave', 'walk'].map((x) => (
                            <LemonButton key={x} type="secondary" size="small" onClick={() => actor.setAnimation(x)}>
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
            {actor.render({ onClick })}
        </Popover>
    )
}

export function HedgehogBuddyWithLogic(): JSX.Element {
    const { hedgehogModeEnabled } = useValues(hedgehogbuddyLogic)
    const { setHedgehogModeEnabled } = useActions(hedgehogbuddyLogic)

    return hedgehogModeEnabled ? <HedgehogBuddy onClose={() => setHedgehogModeEnabled(false)} /> : <></>
}
