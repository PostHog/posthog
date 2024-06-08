import './HedgehogBuddy.scss'

import { ProfilePicture } from '@posthog/lemon-ui'
import { useActions, useValues, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { range, sampleOne, shouldIgnoreInput } from 'lib/utils'
import { ForwardedRef, useEffect, useRef, useState } from 'react'
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
const boundaryPadding = 20
const FPS = 24
const GRAVITY_PIXELS = 10
const MAX_JUMP_COUNT = 2
const COLLISION_DETECTION_DISTANCE_INCREMENT = SPRITE_SIZE / 2

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

export class HedgehogActor {
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
    ground: Element | null = null
    jumpCount = 0
    animationName: string = 'fall'
    animation = this.animations[this.animationName]
    animationFrame = 0
    animationIterations: number | null = null
    animationCompletionHandler?: () => boolean | void

    // properties synced with the logic
    hedgehogConfig: Partial<HedgehogConfig> = {}

    constructor() {
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

    private log(message: string): void {
        if ((window as any)._posthogDebugHedgehog) {
            // eslint-disable-next-line no-console
            console.log(`[HedgehogActor] ${message}`)
        }
    }

    setOnFire(times = 3): void {
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
                if (this.animationName !== 'wave') {
                    this.setAnimation('wave')
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
            if (shouldIgnoreInput(e) || !this.hedgehogConfig.controls_enabled) {
                return
            }

            const key = e.key.toLowerCase()

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
        } else {
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
        this.jumpCount += 1
        this.yVelocity = -GRAVITY_PIXELS * 5
    }

    update(): void {
        this.applyGravity()

        // Ensure we are falling or not
        if (this.animationName === 'fall' && this.ground) {
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
        if (this.isDragging) {
            return
        }

        this.yVelocity += GRAVITY_PIXELS

        const groundBoundingRect = this.detectCollision()

        if (this.ground) {
            if (!groundBoundingRect) {
                this.y = 0
            } else {
                this.y = window.innerHeight - groundBoundingRect.top
            }
            this.jumpCount = 0

            // Apply bounce with friction
            this.yVelocity = -this.yVelocity * 0.4

            if (this.yVelocity > -GRAVITY_PIXELS) {
                // We are so close to the ground that we may as well be on it
                this.yVelocity = 0
            }
        }
    }

    private detectCollision(): DOMRect | null {
        this.ground = null
        if (this.yVelocity < 0) {
            // Don't detect collisions when jumping
            this.y -= this.yVelocity
            return null
        }
        // Apply a granular approach to collision detection to prevent clipping at high speed
        const velocityDirection = Math.sign(this.yVelocity)
        let velocityLeftToApply = Math.abs(this.yVelocity)
        let groundBoundingRect: DOMRect | null = null
        while (velocityLeftToApply > 0) {
            let blocksWithBoundingRects: [Element, DOMRect][] | undefined
            const velocityToApplyInIteration = Math.min(velocityLeftToApply, COLLISION_DETECTION_DISTANCE_INCREMENT)
            velocityLeftToApply -= velocityToApplyInIteration
            this.y -= velocityToApplyInIteration * velocityDirection
            if (this.y <= 0) {
                this.ground = document.body
            } else if (this.hedgehogConfig.interactions_enabled) {
                const hedgehogBoundingRect = {
                    left: this.x,
                    right: this.x + SPRITE_SIZE,
                    top: window.innerHeight - this.y,
                    bottom: window.innerHeight - this.y + SPRITE_SIZE,
                }
                if (!blocksWithBoundingRects) {
                    // Only calculate block bounding rects once we need to
                    blocksWithBoundingRects = Array.from(
                        document.querySelectorAll(
                            '.border, .border-t, .LemonButton--primary, .LemonButton--secondary:not(.LemonButton--status-alt:not(.LemonButton--active)), .LemonInput, .LemonSelect, .LemonTable'
                        )
                    ).map((block) => [block, block.getBoundingClientRect()])
                }
                for (const [block, blockBoundingRect] of blocksWithBoundingRects) {
                    if (
                        // Only allow standing on reasonably wide blocks
                        blockBoundingRect.width > SPRITE_SIZE / 2 &&
                        // Use block as ground when the hedgehog intersects the top border, but not the bottom
                        hedgehogBoundingRect.top < blockBoundingRect.top + SPRITE_SIZE &&
                        hedgehogBoundingRect.bottom > blockBoundingRect.top + SPRITE_SIZE &&
                        // Ensure alignment in the X axis too
                        hedgehogBoundingRect.left < blockBoundingRect.right &&
                        hedgehogBoundingRect.right > blockBoundingRect.left
                    ) {
                        this.ground = block
                        groundBoundingRect = blockBoundingRect
                    }
                }
            }
        }
        // Adjust bounce basis velocity appropriately based on where collusion occurred
        // (i.e. if collision happened earlier in acceleration, bounce should be reduced)
        this.yVelocity -= velocityLeftToApply * velocityDirection
        return groundBoundingRect
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
            <div
                ref={ref}
                className="HedgehogBuddy"
                data-content={preloadContent}
                onMouseDown={(e) => {
                    if (e.button !== 0) {
                        return
                    }
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
                    bottom: this.y - SHADOW_HEIGHT / 2,
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

    const memberHedgehogConfig: HedgehogConfig = {
        ...hedgehogConfig,
        ...member.user.hedgehog_config,
        controls_enabled: false,
    }

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
