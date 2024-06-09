import './HedgehogBuddy.scss'

import { ProfilePicture } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { range, sampleOne, shouldIgnoreInput } from 'lib/utils'
import { ForwardedRef, useEffect, useMemo, useRef, useState } from 'react'
import React from 'react'

import { HedgehogConfig, OrganizationMemberType } from '~/types'

import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { COLOR_TO_FILTER_MAP, hedgehogBuddyLogic } from './hedgehogBuddyLogic'
import { HedgehogOptions } from './HedgehogOptions'
import {
    AccessoryInfo,
    baseSpriteAccessoriesPath,
    baseSpritePath,
    SHADOW_HEIGHT,
    SPRITE_SHEET_WIDTH,
    SPRITE_SIZE,
    standardAccessories,
    standardAnimations,
} from './sprites/sprites'

const xFrames = SPRITE_SHEET_WIDTH / SPRITE_SIZE
const FPS = 24
const GRAVITY_PIXELS = 10
const MAX_JUMP_COUNT = 2

const randomChoiceList: string[] = Object.keys(standardAnimations).reduce((acc: string[], key: string) => {
    return [...acc, ...range(standardAnimations[key].randomChance || 0).map(() => key)]
}, [])

export type HedgehogBuddyProps = {
    onActorLoaded?: (actor: HedgehogActor) => void
    onClose?: () => void
    onClick?: () => void
    onPositionChange?: (actor: HedgehogActor) => void
    hedgehogConfig?: HedgehogConfig
}

type Box = {
    // Simplified rect based on bottom left xy and width/height
    x: number
    y: number
    width: number
    height: number
}

const elementToBox = (element: Element): Box => {
    if (element === document.body) {
        return {
            x: 0,
            y: -1000,
            width: window.innerWidth,
            height: 1000,
        }
    }
    const isHedgehog = element.classList.contains('HedgehogBuddy')
    const rect = element.getBoundingClientRect()
    return {
        x: rect.left + (isHedgehog ? 20 : 0),
        y: window.innerHeight - rect.bottom + (isHedgehog ? 5 : 0),
        width: rect.width - (isHedgehog ? 40 : 0),
        height: rect.height - (isHedgehog ? 30 : 0),
    }
}

export class HedgehogActor {
    element?: HTMLDivElement | null
    animations = standardAnimations
    direction: 'left' | 'right' = 'right'
    startX = Math.min(Math.max(0, Math.floor(Math.random() * window.innerWidth)), window.innerWidth - SPRITE_SIZE)
    startY = Math.min(Math.max(0, Math.floor(Math.random() * window.innerHeight)), window.innerHeight - SPRITE_SIZE)
    x = this.startX
    y = this.startY
    isDragging = false
    isControlledByUser = false
    yVelocity = -30 // Appears as if jumping out of thin air
    xVelocity = 0
    ground: Element | null = null
    jumpCount = 0
    animationName: string = 'fall'
    animation = this.animations[this.animationName]
    animationFrame = 0
    animationIterations: number | null = null
    animationCompletionHandler?: () => boolean | void
    ignoreGroundAboveY?: number

    // properties synced with the logic
    hedgehogConfig: Partial<HedgehogConfig> = {}

    constructor() {
        ;(window as any)._posthogDebugHedgehog = true
        this.setAnimation('fall')
    }

    private accessories(): AccessoryInfo[] {
        return this.hedgehogConfig.accessories?.map((acc) => standardAccessories[acc]) ?? []
    }

    private getAnimationOptions(): string[] {
        if (!this.hedgehogConfig.walking_enabled) {
            return randomChoiceList.filter((x) => x !== 'walk')
        }
        return randomChoiceList
    }

    private log(message: string, ...args: any[]): void {
        if ((window as any)._posthogDebugHedgehog) {
            // eslint-disable-next-line no-console
            console.log(`[HedgehogActor] ${message}`, ...args)
        }
    }

    setOnFire(times = 3): void {
        this.log('setting on fire, iterations remaining:', times)
        this.setAnimation('heatmaps', {
            onComplete: () => {
                if (times == 1) {
                    return
                }
                this.setOnFire(times - 1)
                return true
            },
        })
        this.direction = sampleOne(['left', 'right'])
        this.xVelocity = this.direction === 'left' ? -5 : 5
        this.jump()
    }

    setupKeyboardListeners(): () => void {
        const keyDownListener = (e: KeyboardEvent): void => {
            if (shouldIgnoreInput(e) || !this.hedgehogConfig.controls_enabled) {
                return
            }

            const key = e.key.toLowerCase()

            if ([' ', 'w', 'arrowup'].includes(key)) {
                this.jump()
            }

            if (['arrowdown', 's'].includes(key)) {
                if (this.ground === document.body) {
                    if (this.animationName !== 'wave') {
                        this.setAnimation('wave')
                    }
                } else if (this.ground) {
                    const box = elementToBox(this.ground)
                    this.ignoreGroundAboveY = box.y + box.height - SPRITE_SIZE
                    this.ground = null
                    this.setAnimation('fall')
                }
            }

            if (['arrowleft', 'a', 'arrowright', 'd'].includes(key)) {
                this.isControlledByUser = true
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
            if (shouldIgnoreInput(e) || !this.hedgehogConfig.controls_enabled) {
                return
            }

            const key = e.key.toLowerCase()

            if (['arrowleft', 'a', 'arrowright', 'd'].includes(key)) {
                this.setAnimation('stop')
                this.animationIterations = FPS * 2 // Wait 2 seconds before doing something else
                this.isControlledByUser = false
            }
        }

        window.addEventListener('keydown', keyDownListener)
        window.addEventListener('keyup', keyUpListener)

        return () => {
            window.removeEventListener('keydown', keyDownListener)
            window.removeEventListener('keyup', keyUpListener)
        }
    }

    setAnimation(
        animationName: string,
        options?: {
            onComplete: () => boolean | void
        }
    ): void {
        this.animationName = animationName
        this.animation = this.animations[animationName]
        this.animationFrame = 0
        this.animationCompletionHandler = () => {
            console.log(
                'clearing animation completion handler',
                !!this.animationCompletionHandler,
                !!options?.onComplete
            )
            this.animationCompletionHandler = undefined

            return options?.onComplete()
        }
        if (this.animationName !== 'stop') {
            this.direction = this.animation.forceDirection || sampleOne(['left', 'right'])
        }

        // Set a random number of iterations or infinite for certain situations
        this.animationIterations = this.animation.maxIteration
            ? Math.max(1, Math.floor(Math.random() * this.animation.maxIteration))
            : null

        if (animationName === 'walk') {
            this.xVelocity = this.direction === 'left' ? -1 : 1
        } else if (animationName === 'stop' && !this.isControlledByUser) {
            this.xVelocity = 0
        }

        if (window.JS_POSTHOG_SELF_CAPTURE || (window as any).debugHedgehog) {
            const duration = this.animationIterations
                ? this.animationIterations * this.animation.frames * (1000 / FPS)
                : '∞'

            this.log(`Will '${this.animationName}' for ${duration}ms`)
        }
    }

    setRandomAnimation(): void {
        if (this.animationName !== 'stop') {
            this.setAnimation('stop')
        } else {
            this.setAnimation(sampleOne(this.getAnimationOptions()))
        }
    }

    jump(): void {
        if (this.jumpCount >= MAX_JUMP_COUNT) {
            return
        }
        this.ground = null
        this.jumpCount += 1
        this.yVelocity = GRAVITY_PIXELS * 5
    }

    update(): void {
        this.applyVelocity()

        // Ensure we are falling or not
        if (this.animationName === 'fall' && !this.isFalling) {
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

                const preventNextAnimation = this.animationCompletionHandler?.()
                if (!preventNextAnimation) {
                    this.setRandomAnimation()
                }
            }

            this.animationFrame = 0
        }

        this.x = this.x + this.xVelocity

        if (this.x < 0) {
            this.x = 0
            if (!this.isControlledByUser) {
                this.xVelocity = -this.xVelocity
                this.direction = 'right'
            }
        }

        if (this.x > window.innerWidth - SPRITE_SIZE) {
            this.x = window.innerWidth - SPRITE_SIZE
            if (!this.isControlledByUser) {
                this.xVelocity = -this.xVelocity
                this.direction = 'left'
            }
        }
    }

    private applyVelocity(): void {
        if (this.isDragging) {
            this.ground = null
            return
        }

        this.ground = this.findGround()
        this.yVelocity -= GRAVITY_PIXELS

        // We decelerate the x velocity if the hedgehog is doing anything except moving or falling
        if (['stop'].includes(this.animationName) && !this.isControlledByUser) {
            this.xVelocity = this.xVelocity * 0.6
        }

        let newY = this.y + this.yVelocity

        if (this.yVelocity < 0) {
            // We are falling - detect ground
            const groundBoundingRect = elementToBox(this.ground)
            const groundY = groundBoundingRect.y + groundBoundingRect.height

            if (newY <= groundY) {
                // Next frame would put it below the ground so we apply
                newY = groundY
                this.yVelocity = -this.yVelocity * 0.4

                // Clear flags as we have hit the ground
                this.ignoreGroundAboveY = undefined
                this.jumpCount = 0
            }
        } else {
            // If we are going up we can reset the ground
            this.ground = null
        }

        this.y = newY
    }

    private findGround(): Element {
        // We reset the ground when he is moved or x changes

        if (!this.hedgehogConfig.interactions_enabled || !this.element || this.y <= 0) {
            return document.body
        }

        const hedgehogBox = elementToBox(this.element)

        if (this.ground && this.ground !== document.body) {
            // Check if the current ground is still valid - if so we stick with it to stop flickering
            const groundBoundingRect = elementToBox(this.ground)

            if (
                hedgehogBox.x + hedgehogBox.width > groundBoundingRect.x &&
                hedgehogBox.x < groundBoundingRect.x + groundBoundingRect.width &&
                // Check still on screen
                groundBoundingRect.y + groundBoundingRect.height + hedgehogBox.height < window.innerHeight &&
                groundBoundingRect.y >= 0
            ) {
                // We are still on the same ground
                return this.ground
            }
        }

        // Only calculate block bounding rects once we need to
        const blocksWithBoxes: [Element, Box][] = Array.from(
            document.querySelectorAll(
                '.border, .border-t, .LemonButton--primary, .LemonButton--secondary:not(.LemonButton--status-alt:not(.LemonButton--active)), .LemonInput, .LemonSelect, .LemonTable, .HedgehogBuddy'
            )
        )
            .filter((x) => x !== this.element)
            .map((block) => [block, elementToBox(block)])

        // The highest candidate is our new ground
        let highestCandidate: [Element, Box] | null = null

        blocksWithBoxes.forEach(([block, box]) => {
            if (box.y + box.height > window.innerHeight || box.y < 0) {
                return
            }

            if (this.ignoreGroundAboveY && box.y + box.height > this.ignoreGroundAboveY) {
                return
            }

            const isAboveOrOn =
                hedgehogBox.x + hedgehogBox.width > box.x &&
                hedgehogBox.x < box.x + box.width &&
                hedgehogBox.y >= box.y + box.height

            if (isAboveOrOn) {
                if (!highestCandidate || box.y > highestCandidate[1].y) {
                    highestCandidate = [block, box]
                }
            }
        })

        return highestCandidate?.[0] ?? document.body
    }

    private get onGround(): boolean {
        if (this.ground) {
            const groundLevel = elementToBox(this.ground).y + elementToBox(this.ground).height
            return this.y <= groundLevel
        }

        return false
    }

    private get isFalling(): boolean {
        return !this.onGround && Math.abs(this.yVelocity) > 1
    }

    render({ onClick, ref }: { onClick: () => void; ref: ForwardedRef<HTMLDivElement> }): JSX.Element {
        const accessoryPosition = this.animation.accessoryPositions?.[this.animationFrame]
        const preloadContent =
            Object.values(this.animations)
                .map((x) => `url(${baseSpritePath()}/${x.img}.png)`)
                .join(' ') +
            ' ' +
            this.accessories()
                .map((accessory) => `url(${baseSpriteAccessoriesPath}/${accessory.img}.png)`)
                .join(' ')

        const imageFilter = this.hedgehogConfig.color ? COLOR_TO_FILTER_MAP[this.hedgehogConfig.color] : undefined

        return (
            <>
                <div
                    ref={(r) => {
                        this.element = r
                        if (r) {
                            // TODO: Fix this
                            ref?.(r)
                        }
                    }}
                    className="HedgehogBuddy"
                    data-content={preloadContent}
                    onMouseDown={(e) => {
                        if (e.button !== 0) {
                            return
                        }
                        let moved = false
                        const lastMoves: [number, number][] = []

                        const onMouseMove = (e: any): void => {
                            moved = true
                            this.isDragging = true
                            this.setAnimation('fall')
                            this.x = e.clientX - SPRITE_SIZE / 2
                            this.y = window.innerHeight - e.clientY - SPRITE_SIZE / 2

                            if (lastMoves.length > 5) {
                                lastMoves.shift()
                            }
                            // -2 multiple makes it feel more responsive
                            lastMoves.push([e.movementX, e.movementY * -2])
                        }

                        const onWindowUp = (): void => {
                            if (!moved) {
                                onClick()
                            }
                            this.isDragging = false

                            // use the average of the last moves
                            this.xVelocity = lastMoves.reduce((acc, [x]) => acc + x, 0) / lastMoves.length
                            this.yVelocity = lastMoves.reduce((acc, [, y]) => acc + y, 0) / lastMoves.length

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
                        bottom: this.y - SHADOW_HEIGHT * 0.5,
                        transition: !this.isDragging ? `all ${1000 / FPS}ms` : undefined,
                        transform: `scaleX(${this.direction === 'right' ? 1 : -1})`,
                        cursor: 'pointer',
                        margin: 0,
                    }}
                >
                    <div
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            imageRendering: 'pixelated',
                            width: SPRITE_SIZE,
                            height: SPRITE_SIZE,
                            backgroundImage: `url(${baseSpritePath()}/${this.animation.img}.png)`,
                            backgroundPosition: `-${(this.animationFrame % xFrames) * SPRITE_SIZE}px -${
                                Math.floor(this.animationFrame / xFrames) * SPRITE_SIZE
                            }px`,
                            filter: imageFilter as any,
                        }}
                    />
                    {this.accessories().map((accessory, index) => (
                        <div
                            key={index}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                position: 'absolute',
                                top: 0,
                                left: 0,
                                imageRendering: 'pixelated',
                                width: SPRITE_SIZE,
                                height: SPRITE_SIZE,
                                backgroundImage: `url(${baseSpriteAccessoriesPath()}/${accessory.img}.png)`,
                                transform: accessoryPosition
                                    ? `translate3d(${accessoryPosition[0]}px, ${accessoryPosition[1]}px, 0)`
                                    : undefined,
                                filter: imageFilter as any,
                            }}
                        />
                    ))}
                </div>
                {(window as any)._posthogDebugHedgehog && (
                    <>
                        {[this.element && elementToBox(this.element), this.ground && elementToBox(this.ground)].map(
                            (box, i) => {
                                if (!box) {
                                    return
                                }
                                return (
                                    <div
                                        key={i}
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{
                                            outline: '1px solid red',
                                            position: 'fixed',
                                            pointerEvents: 'none',
                                            top: window.innerHeight - box.y - box.height,
                                            left: box.x,
                                            width: box.width,
                                            height: box.height,
                                        }}
                                    />
                                )
                            }
                        )}
                    </>
                )}
            </>
        )
    }
}

export const HedgehogBuddy = React.forwardRef<HTMLDivElement, HedgehogBuddyProps>(function HedgehogBuddy(
    { onActorLoaded, onClick: _onClick, onPositionChange, hedgehogConfig },
    ref
): JSX.Element {
    const actorRef = useRef<HedgehogActor>()

    if (!actorRef.current) {
        actorRef.current = new HedgehogActor()
        onActorLoaded?.(actorRef.current)
    }

    const actor = actorRef.current
    const [_, setTimerLoop] = useState(0)
    const { currentLocation } = useValues(router)

    useEffect(() => {
        if (currentLocation.pathname.includes('/heatmaps')) {
            actor?.setOnFire()
        }
    }, [currentLocation.pathname])

    useEffect(() => {
        if (hedgehogConfig) {
            console.log('UPDATED CONNFIG', hedgehogConfig)
            actor.hedgehogConfig = hedgehogConfig
            actor.setAnimation(hedgehogConfig.walking_enabled ? 'walk' : 'stop')
        }
    }, [hedgehogConfig])

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

    useEffect(() => {
        onPositionChange?.(actor)
    }, [actor.x, actor.y])

    const onClick = (): void => {
        !actor.isDragging && _onClick?.()
    }

    return actor.render({ onClick, ref })
})

export function MyHedgehogBuddy({
    onActorLoaded,
    onClose,
    onClick: _onClick,
    onPositionChange,
}: HedgehogBuddyProps): JSX.Element {
    const [actor, setActor] = useState<HedgehogActor | null>(null)
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)

    useEffect(() => {
        return actor?.setupKeyboardListeners()
    }, [actor])

    const [popoverVisible, setPopoverVisible] = useState(false)

    const onClick = (): void => {
        setPopoverVisible(!popoverVisible)
        _onClick?.()
    }
    const disappear = (): void => {
        setPopoverVisible(false)
        actor?.setAnimation('wave')
        setTimeout(() => onClose?.(), (actor!.animations.wave.frames * 1000) / FPS)
    }

    return (
        <Popover
            onClickOutside={() => setPopoverVisible(false)}
            visible={popoverVisible}
            placement="top"
            fallbackPlacements={['bottom', 'left', 'right']}
            overflowHidden
            overlay={
                <div className="max-w-140 flex flex-col flex-1 overflow-hidden">
                    <ScrollableShadows className="flex-1 overflow-y-auto" direction="vertical">
                        <div className="p-2">
                            <HedgehogOptions />
                        </div>
                    </ScrollableShadows>
                    <div className="flex shrink-0 justify-end gap-2 p-2 border-t">
                        <LemonButton type="secondary" status="danger" onClick={disappear}>
                            Good bye!
                        </LemonButton>
                        <LemonButton type="secondary" onClick={() => setPopoverVisible(false)}>
                            Carry on!
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <HedgehogBuddy
                onActorLoaded={(actor) => {
                    setActor(actor)
                    onActorLoaded?.(actor)
                }}
                onClick={onClick}
                onPositionChange={onPositionChange}
                hedgehogConfig={hedgehogConfig}
            />
        </Popover>
    )
}

export function MemberHedgehogBuddy({ member }: { member: OrganizationMemberType }): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { patchHedgehogConfig } = useActions(hedgehogBuddyLogic)
    const [popoverVisible, setPopoverVisible] = useState(false)

    const memberHedgehogConfig: HedgehogConfig = useMemo(
        () => ({
            ...hedgehogConfig,
            ...member.user.hedgehog_config,
            controls_enabled: false,
        }),
        [hedgehogConfig, member.user.hedgehog_config]
    )

    const onClick = (): void => {
        setPopoverVisible(!popoverVisible)
    }
    return (
        <Popover
            onClickOutside={() => setPopoverVisible(false)}
            visible={popoverVisible}
            placement="top"
            fallbackPlacements={['bottom', 'left', 'right']}
            overflowHidden
            overlay={
                <div className="min-w-50 max-w-140">
                    <div className="p-3">
                        <ProfilePicture user={member.user} size="xl" showName />
                    </div>

                    <div className="flex items-end gap-2 border-t p-3">
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() =>
                                patchHedgehogConfig({
                                    party_mode_enabled: false,
                                })
                            }
                        >
                            Turn off party mode
                        </LemonButton>
                        <LemonButton type="primary" size="small" onClick={() => setPopoverVisible(false)}>
                            Carry on!
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <HedgehogBuddy onClick={onClick} hedgehogConfig={memberHedgehogConfig} />
        </Popover>
    )
}
